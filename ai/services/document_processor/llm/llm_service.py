import logging
from typing import Optional, AsyncIterator
from config import settings
import asyncio
import json

from .provider_adapters import (
    create_adapter_for_provider,
    LLMProviderAdapter,
    PROMPT_TYPE_CLASSIFICATION,
    PROMPT_TYPE_SHORT_DIRECT,
    PROMPT_TYPE_DOCUMENT_LISTING,
    PROMPT_TYPE_RAG,
)

logger = logging.getLogger(__name__)


class LLMService:
    """Service for managing LLM interactions (Ollama | Gemini | Groq). Uses provider adapter for limits and truncation."""

    def __init__(
        self,
        ollama_base_url: str,
        ollama_model: str,
        gemini_api_key: Optional[str] = None,
        gemini_model: str = "gemini-2.5-pro",
        groq_api_key: Optional[str] = None,
        groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        provider: str = "ollama",
        adapter: Optional[LLMProviderAdapter] = None,
    ):
        self.base_url = ollama_base_url
        self.model = ollama_model
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.groq_api_key = groq_api_key or ""
        self.groq_model = groq_model
        self.http_client = None
        self._gemini = None
        self._groq = None
        self.provider = provider.lower().strip()
        self._adapter: LLMProviderAdapter = adapter or create_adapter_for_provider(self.provider, settings)
        logger.info(f"LLMService initialized with provider: {self.provider}")
        # Lazy initialization per provider

    def get_max_listing_context_chars(self) -> int:
        """Max chars for document listing context so all files fit in one prompt. Used by orchestrator."""
        return self._adapter.get_max_listing_context_chars()

    def _initialize_client(self):
        """Initialize client for the selected provider (lazy)."""
        if self.provider == "groq":
            if self._groq is not None:
                return
            try:
                from groq import AsyncGroq
                if not self.groq_api_key:
                    raise RuntimeError("GROQ_API_KEY is not set")
                self._groq = AsyncGroq(api_key=self.groq_api_key)
                logger.info(f"Groq client initialized with model: {self.groq_model}")
            except Exception as e:
                logger.error(f"Failed to initialize Groq: {e}")
                raise
        elif self.provider == "gemini":
            if self._gemini is not None:
                return
            try:
                import google.generativeai as genai
                if not self.gemini_api_key:
                    raise RuntimeError("GEMINI_API_KEY is not set")
                genai.configure(api_key=self.gemini_api_key)
                max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
                self._gemini = genai.GenerativeModel(
                    self.gemini_model,
                    generation_config={
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "max_output_tokens": max_tokens,  # Same knob as Ollama; avoids cut-off for long lists
                    }
                )
                logger.info(f"Gemini initialized with model: {self.gemini_model}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                raise
        else:
            if self.http_client is not None:
                return  # Already initialized
            try:
                import httpx
                self.http_client = httpx.AsyncClient(timeout=30.0)
                logger.info(f"Ollama client initialized with model: {self.model}")
            except Exception as e:
                logger.error(f"Failed to initialize Ollama client: {e}")
                raise
    
    async def generate_response(self, query: str, context: str, conversation_history: list = None) -> str:
        """Generate response using selected provider."""
        try:
            self._initialize_client()
            context = self._adapter.truncate_context(context)
            prompt = self._build_prompt(query, context, conversation_history or [])

            if self.provider == "gemini":
                try:
                    max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
                    generation_config = {"temperature": 0.7, "top_p": 0.9, "max_output_tokens": max_tokens}
                    result = await asyncio.to_thread(
                        self._gemini.generate_content, prompt, generation_config=generation_config
                    )
                    text = getattr(result, "text", None)
                    if not text:
                        # Fallback: attempt to extract from candidates/parts
                        candidates = getattr(result, "candidates", []) or []
                        for c in candidates:
                            content = getattr(c, "content", None)
                            parts = getattr(content, "parts", []) if content else []
                            part_texts = [getattr(p, "text", "") for p in parts]
                            joined = "".join(part_texts).strip()
                            if joined:
                                text = joined
                                break
                    return text or "I couldn't generate a response."
                except Exception as ge:
                    logger.error(f"Gemini generation error: {ge}")
                    return "I couldn't generate a response due to an AI provider error."

            if self.provider == "groq":
                try:
                    max_tokens = self._adapter.get_max_output_tokens(PROMPT_TYPE_RAG)
                    completion = await self._groq.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.groq_model,
                        temperature=0.7,
                        max_completion_tokens=max_tokens,
                        stream=False,
                    )
                    text = (completion.choices[0].message.content or "").strip()
                    return text or "I couldn't generate a response."
                except Exception as ge:
                    logger.error(f"Groq generation error: {ge}")
                    return "I couldn't generate a response due to an AI provider error."

            # Default: Ollama
            max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
            response = await self.http_client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "max_tokens": max_tokens
                    }
                }
            )
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "I couldn't generate a response.")
            else:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                return "I couldn't generate a response due to an API error."

        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            return "I couldn't generate a response due to an error."

    async def generate_response_stream(
        self, query: str, context: str, conversation_history: list = None
    ) -> AsyncIterator[str]:
        """
        Stream response tokens from the LLM. Yields text chunks.
        Ollama: true streaming. Gemini: yields full message in one chunk (no streaming API in current SDK usage).
        """
        try:
            self._initialize_client()
            context = self._adapter.truncate_context(context)
            prompt = self._build_prompt(query, context, conversation_history or [])

            if self.provider == "gemini":
                # Gemini SDK (google.generativeai) - no async stream in this codebase; yield full response as one chunk
                try:
                    max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
                    generation_config = {"temperature": 0.7, "top_p": 0.9, "max_output_tokens": max_tokens}
                    result = await asyncio.to_thread(
                        self._gemini.generate_content, prompt, generation_config=generation_config
                    )
                    text = getattr(result, "text", None)
                    if not text:
                        candidates = getattr(result, "candidates", []) or []
                        for c in candidates:
                            content = getattr(c, "content", None)
                            parts = getattr(content, "parts", []) if content else []
                            part_texts = [getattr(p, "text", "") for p in parts]
                            joined = "".join(part_texts).strip()
                            if joined:
                                text = joined
                                break
                    if text:
                        yield text
                    else:
                        yield "I couldn't generate a response."
                except Exception as ge:
                    logger.error(f"Gemini generation error: {ge}")
                    yield "I couldn't generate a response due to an AI provider error."
                return

            if self.provider == "groq":
                try:
                    max_tokens = self._adapter.get_max_output_tokens(PROMPT_TYPE_RAG)
                    stream = await self._groq.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.groq_model,
                        temperature=0.7,
                        max_completion_tokens=max_tokens,
                        stream=True,
                    )
                    async for chunk in stream:
                        delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                        if delta:
                            yield delta
                except Exception as ge:
                    logger.error(f"Groq stream error: {ge}")
                    yield "I couldn't generate a response due to an AI provider error."
                return

            # Ollama: stream=true returns newline-delimited JSON
            max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
            async with self.http_client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "max_tokens": max_tokens,
                    },
                },
                timeout=60.0,
            ) as response:
                if response.status_code != 200:
                    logger.error(f"Ollama stream error: {response.status_code}")
                    yield "I couldn't generate a response due to an API error."
                    return
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        delta = data.get("response") or ""
                        if delta:
                            yield delta
                        if data.get("done"):
                            return
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error in LLM stream: {e}")
            yield "I couldn't generate a response due to an error."

    async def generate_simple(
        self,
        prompt: str,
        prompt_type: str = PROMPT_TYPE_CLASSIFICATION,
        max_completion_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate a simple response without context/prompt templating.
        prompt_type: classification | short_direct | document_listing (adapter picks output token limit).
        max_completion_tokens: override adapter default when set.
        """
        try:
            self._initialize_client()
            prompt = self._adapter.truncate_prompt(prompt)
            out_tokens = max_completion_tokens if max_completion_tokens is not None else self._adapter.get_max_output_tokens(prompt_type)

            if self.provider == "gemini":
                if not self._gemini:
                    logger.error("Gemini client not initialized")
                    return "I couldn't generate a response."

                try:
                    response = await asyncio.to_thread(
                        self._gemini.generate_content,
                        prompt
                        # No generation_config - use model defaults
                    )
                    
                    # Extract text from response
                    text = None
                    
                    # Method 1: Direct text attribute (most common)
                    if hasattr(response, 'text'):
                        try:
                            text = response.text.strip()
                        except Exception as e:
                            logger.warning(f"Failed to access .text: {e}")
                    
                    # Method 2: Candidates (fallback)
                    if not text and hasattr(response, 'candidates'):
                        try:
                            if response.candidates:
                                candidate = response.candidates[0]
                                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                                    text = ''.join(part.text for part in candidate.content.parts if hasattr(part, 'text')).strip()
                        except Exception as e:
                            logger.warning(f"Failed to access .candidates: {e}")
                    
                    if text:
                        return text
                    else:
                        logger.error(f"Could not extract text from Gemini response. Finish reason: {getattr(response.candidates[0] if response.candidates else None, 'finish_reason', 'UNKNOWN')}")
                        return "I couldn't generate a response."
                        
                except Exception as ge:
                    logger.error(f"Gemini generation error: {ge}")
                    logger.error(f"Error type: {type(ge)}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    return "I couldn't generate a response due to an AI provider error."

            if self.provider == "groq":
                try:
                    completion = await self._groq.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.groq_model,
                        temperature=0.1,
                        max_completion_tokens=out_tokens,
                        stream=False,
                    )
                    text = (completion.choices[0].message.content or "").strip()
                    return text or "I couldn't generate a response."
                except Exception as ge:
                    logger.error(f"Groq simple generation error: {ge}")
                    return "I couldn't generate a response due to an AI provider error."

            # Default: Ollama
            response = await self.http_client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "top_p": 0.9,
                        "max_tokens": out_tokens,
                    },
                },
            )
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "I couldn't generate a response.")
            else:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                return "I couldn't generate a response due to an API error."

        except Exception as e:
            logger.error(f"Error generating simple LLM response: {e}")
            return "I couldn't generate a response due to an error."

    def _build_prompt(self, query: str, context: str, conversation_history: list = None) -> str:
        """Build the prompt for the LLM with conversation history."""
        conversation_history = conversation_history or []

        conversation_context = ""
        if conversation_history:
            conversation_context = "\n\nPrevious conversation:\n"
            for msg in conversation_history:
                role = "User" if msg["role"] == "user" else "Assistant"
                conversation_context += f"{role}: {msg['content']}\n"

        return f"""Answer the question using ONLY the document context below. Cite sources as [Document: filename].
{conversation_context}
Context:
{context}

Question: {query}

Rules:
- Combine information from multiple chunks of the same document into one answer
- When asked for a list, include every matching item from the context
- If the context doesn't contain the answer, say so
- Use specific details and quotes when relevant

Answer:"""
    
    def update_model(self, new_model: str):
        """Update the LLM model"""
        self.model = new_model
        logger.info(f"LLM model updated to: {new_model}")
    
    def update_base_url(self, new_url: str):
        """Update the Ollama base URL"""
        self.base_url = new_url
        logger.info(f"Ollama base URL updated to: {new_url}")
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.http_client:
                await self.http_client.aclose()
                self.http_client = None
            # Gemini has no persistent client to close
        except Exception as e:
            logger.error(f"Error during LLM service cleanup: {e}")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
