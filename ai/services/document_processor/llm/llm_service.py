import logging
from typing import Any, Dict, List, Optional, Tuple, AsyncIterator
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
        # Approximate token usage tracking (per process, best-effort; mainly for Groq).
        # Keys: prompt, completion, total.
        self._token_usage: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        logger.info(f"LLMService initialized with provider: {self.provider}")
        # Lazy initialization per provider

    def get_max_listing_context_chars(self) -> int:
        """Max chars for document listing context so all files fit in one prompt. Used by orchestrator."""
        return self._adapter.get_max_listing_context_chars()

    def supports_tool_calling(self) -> bool:
        """True if this provider supports native tool/function calling (e.g. Groq). Enables single-loop agent flow."""
        return self._adapter.supports_tool_calling()

    def _estimate_tokens_from_chars(self, text: str) -> int:
        """Rough token estimate from character length (4 chars ≈ 1 token for English)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def _record_usage(self, prompt_tokens: int, completion_tokens: int, label: str = "") -> None:
        """Update internal token counters and log usage."""
        try:
            p = int(prompt_tokens or 0)
            c = int(completion_tokens or 0)
        except Exception:
            p, c = 0, 0
        t = p + c
        self._token_usage["prompt"] += p
        self._token_usage["completion"] += c
        self._token_usage["total"] += t
        logger.info(
            "LLM token usage%s: prompt=%s, completion=%s, total=%s (cumulative total=%s)",
            f" ({label})" if label else "",
            p,
            c,
            t,
            self._token_usage["total"],
        )

    def get_token_usage(self) -> Dict[str, int]:
        """Return a snapshot of cumulative token usage for this process."""
        return dict(self._token_usage)

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
    
    def switch_provider(
        self,
        provider: str,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """Switch the active LLM provider (and optionally model/key/url) at runtime.

        Clears cached clients so they are re-initialized on the next call.
        """
        provider = provider.lower().strip()
        if provider not in ("ollama", "gemini", "groq"):
            raise ValueError(f"Unknown provider: {provider!r}. Must be ollama, gemini, or groq.")

        if provider == "ollama":
            if model:
                self.model = model
            if base_url:
                self.base_url = base_url
        elif provider == "gemini":
            if model:
                self.gemini_model = model
            if api_key:
                self.gemini_api_key = api_key
        elif provider == "groq":
            if model:
                self.groq_model = model
            if api_key:
                self.groq_api_key = api_key

        # Reset all cached clients so _initialize_client() rebuilds them
        self.http_client = None
        self._gemini = None
        self._groq = None

        self.provider = provider
        self._adapter = create_adapter_for_provider(self.provider, settings)
        logger.info("LLM provider switched to: %s", self.provider)

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
                    # Token usage (when provided by Groq)
                    usage = getattr(completion, "usage", None)
                    prompt_t = completion_t = 0
                    if usage is not None:
                        # usage may be an object or dict
                        pt = getattr(usage, "prompt_tokens", None)
                        ct = getattr(usage, "completion_tokens", None)
                        if pt is None and isinstance(usage, dict):
                            pt = usage.get("prompt_tokens")
                        if ct is None and isinstance(usage, dict):
                            ct = usage.get("completion_tokens") or usage.get("output_tokens")
                        prompt_t = pt or 0
                        completion_t = ct or 0
                    else:
                        # Fallback: rough estimate from prompt and response lengths
                        text_preview = (completion.choices[0].message.content or "") if completion.choices else ""
                        prompt_t = self._estimate_tokens_from_chars(prompt)
                        completion_t = self._estimate_tokens_from_chars(text_preview)
                    text = (completion.choices[0].message.content or "").strip()
                    self._record_usage(prompt_t, completion_t, label="generate_simple_groq")
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
                    # Approximate streaming usage: estimate from prompt and streamed output length.
                    prompt_tokens_est = self._estimate_tokens_from_chars(prompt)
                    completion_chars = 0
                    async for chunk in stream:
                        delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                        if delta:
                            completion_chars += len(delta)
                            yield delta
                    completion_tokens_est = self._estimate_tokens_from_chars("x" * completion_chars)
                    self._record_usage(prompt_tokens_est, completion_tokens_est, label="generate_response_stream_groq")
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

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
        """
        Phase B.3 – Single-loop tool calling. Send messages + tools; return (content, tool_calls).
        Only supported when provider is Groq. Returns (content, None) or (None, tool_calls) or (content, []).
        tool_calls format: [{"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}, ...].
        """
        if not self.supports_tool_calling():
            logger.warning("chat_with_tools called but provider does not support tool calling")
            return None, None
        try:
            self._initialize_client()
            completion = await self._groq.chat.completions.create(
                messages=messages,
                model=self.groq_model,
                tools=tools,
                tool_choice="auto",
                temperature=0.1,
                max_completion_tokens=max_tokens,
                stream=False,
            )
            # Token usage when Groq provides it
            usage = getattr(completion, "usage", None)
            prompt_t = completion_t = 0
            if usage is not None:
                pt = getattr(usage, "prompt_tokens", None)
                ct = getattr(usage, "completion_tokens", None)
                if pt is None and isinstance(usage, dict):
                    pt = usage.get("prompt_tokens")
                if ct is None and isinstance(usage, dict):
                    ct = usage.get("completion_tokens") or usage.get("output_tokens")
                prompt_t = pt or 0
                completion_t = ct or 0
            else:
                # Rough estimate from all message contents
                all_text = "".join(str(m.get("content", "")) for m in messages)
                prompt_t = self._estimate_tokens_from_chars(all_text)
                # First assistant/tool-call turn is small; completion tokens are minor here
                completion_t = 0
            self._record_usage(prompt_t, completion_t, label="chat_with_tools_groq")
            msg = completion.choices[0].message if completion.choices else None
            if not msg:
                return "I couldn't generate a response.", None
            content = (getattr(msg, "content", None) or "").strip() or None
            raw_tool_calls = getattr(msg, "tool_calls", None) or []
            tool_calls = []
            for tc in raw_tool_calls:
                if not getattr(tc, "id", None) or not getattr(tc, "function", None):
                    continue
                fn = tc.function
                tool_calls.append({
                    "id": tc.id,
                    "type": getattr(tc, "type", "function"),
                    "function": {
                        "name": getattr(fn, "name", ""),
                        "arguments": getattr(fn, "arguments", "") or "{}",
                    },
                })
            return content, tool_calls if tool_calls else None
        except Exception as e:
            err_str = str(e)
            # Groq returns 400 tool_use_failed when the model answers without calling a tool
            # (e.g. "what can you do?"). Retry without tools to get a proper answer.
            if "400" in err_str and "tool_use_failed" in err_str.lower():
                logger.info("chat_with_tools got tool_use_failed; retrying without tools")
                try:
                    content = await self._chat_messages_no_tools(messages, max_tokens)
                    return (content or "I couldn't generate a response.", None)
                except Exception as retry_e:
                    logger.warning("Fallback chat without tools failed: %s", retry_e)
            logger.error(f"chat_with_tools failed: {e}")
            return "I couldn't generate a response due to an error.", None

    async def _chat_messages_no_tools(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> Optional[str]:
        """Groq completion with messages only (no tools). Used when tool call fails with tool_use_failed."""
        if not self.supports_tool_calling():
            return None
        self._initialize_client()
        completion = await self._groq.chat.completions.create(
            messages=messages,
            model=self.groq_model,
            temperature=0.1,
            max_completion_tokens=max_tokens,
            stream=False,
        )
        # Usage for fallback chat
        usage = getattr(completion, "usage", None)
        prompt_t = completion_t = 0
        if usage is not None:
            pt = getattr(usage, "prompt_tokens", None)
            ct = getattr(usage, "completion_tokens", None)
            if pt is None and isinstance(usage, dict):
                pt = usage.get("prompt_tokens")
            if ct is None and isinstance(usage, dict):
                ct = usage.get("completion_tokens") or usage.get("output_tokens")
            prompt_t = pt or 0
            completion_t = ct or 0
        else:
            all_text = "".join(str(m.get("content", "")) for m in messages)
            prompt_t = self._estimate_tokens_from_chars(all_text)
            completion_t = 0
        self._record_usage(prompt_t, completion_t, label="_chat_messages_no_tools_groq")
        msg = completion.choices[0].message if completion.choices else None
        if not msg:
            return None
        return (getattr(msg, "content", None) or "").strip() or None

    async def chat_messages_stream(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """
        Phase B.3 – Stream the final answer from a conversation (e.g. after tool results).
        Takes a list of messages (no tools). Only supported for Groq.
        """
        if not self.supports_tool_calling():
            logger.warning("chat_messages_stream called but provider does not support it")
            return
        try:
            self._initialize_client()
            # Approximate prompt tokens from all messages (system/user/assistant/tool).
            all_text = "".join(str(m.get("content", "")) for m in messages)
            prompt_tokens_est = self._estimate_tokens_from_chars(all_text)
            completion_chars = 0
            stream = await self._groq.chat.completions.create(
                messages=messages,
                model=self.groq_model,
                temperature=0.1,
                max_completion_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    completion_chars += len(delta)
                    yield delta
            completion_tokens_est = self._estimate_tokens_from_chars("x" * completion_chars)
            self._record_usage(prompt_tokens_est, completion_tokens_est, label="chat_messages_stream_groq")
        except Exception as e:
            logger.error(f"chat_messages_stream failed: {e}")
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
                    usage = getattr(completion, "usage", None)
                    prompt_t = completion_t = 0
                    if usage is not None:
                        pt = getattr(usage, "prompt_tokens", None)
                        ct = getattr(usage, "completion_tokens", None)
                        if pt is None and isinstance(usage, dict):
                            pt = usage.get("prompt_tokens")
                        if ct is None and isinstance(usage, dict):
                            ct = usage.get("completion_tokens") or usage.get("output_tokens")
                        prompt_t = pt or 0
                        completion_t = ct or 0
                    else:
                        text_preview = (completion.choices[0].message.content or "") if completion.choices else ""
                        prompt_t = self._estimate_tokens_from_chars(prompt)
                        completion_t = self._estimate_tokens_from_chars(text_preview)
                    text = (completion.choices[0].message.content or "").strip()
                    self._record_usage(prompt_t, completion_t, label="generate_simple_groq")
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
                role = msg.get("role", "user")
                content = (msg.get("content") or "").strip()
                if not content:
                    continue
                if role == "system":
                    conversation_context += f"[Summary of earlier conversation]\n{content}\n\n"
                elif role == "user":
                    conversation_context += f"User: {content}\n"
                else:
                    conversation_context += f"Assistant: {content}\n"

        return f"""Use the document context below when it is relevant to the user's question. Cite sources as [Document: filename].
{conversation_context}
Context:
{context}

Question: {query}

Rules:
- Use the documents when they help answer the question. If the user asks for an overview or explanation of the documents, summarize what is in the context and what the documents are about.
- If the question is general conversation (e.g. greetings, "what's up"), respond normally; do not force document citations.
- Combine information from multiple chunks of the same document into one answer. When asked for a list, include every matching item from the context.
- Only say "the context doesn't contain the answer" when the user clearly asked a factual question that is not in the context.
- Use specific details and quotes when relevant.

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
