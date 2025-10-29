import logging
from typing import Optional
from config import settings
import asyncio


logger = logging.getLogger(__name__)


class LLMService:
    """Service for managing LLM interactions (Ollama | Gemini)"""

    def __init__(self, ollama_base_url: str, ollama_model: str, gemini_api_key: Optional[str] = None, gemini_model: str = "gemini-2.5-pro", provider: str = "ollama"):
        self.base_url = ollama_base_url
        self.model = ollama_model
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.http_client = None
        self._gemini = None
        self.provider = provider.lower().strip()
        logger.info(f"LLMService initialized with provider: {self.provider}")
        # Lazy initialization per provider
    
    def _initialize_client(self):
        """Initialize client for the selected provider (lazy)."""
        if self.provider == "gemini":
            if self._gemini is not None:
                return
            try:
                import google.generativeai as genai
                if not self.gemini_api_key:
                    raise RuntimeError("GEMINI_API_KEY is not set")
                genai.configure(api_key=self.gemini_api_key)
                # Configure model with sane defaults
                self._gemini = genai.GenerativeModel(
                    self.gemini_model,
                    generation_config={
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "max_output_tokens": 8192,  # Increased to handle longer responses
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
    
    async def generate_response(self, query: str, context: str) -> str:
        """Generate response using selected provider."""
        try:
            self._initialize_client()
            prompt = self._build_prompt(query, context)

            if self.provider == "gemini":
                try:
                    # Run blocking SDK call in a thread to avoid blocking the event loop
                    result = await asyncio.to_thread(self._gemini.generate_content, prompt)
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

            # Default: Ollama
            response = await self.http_client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "max_tokens": 1000
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
    
    async def generate_simple(self, prompt: str) -> str:
        """
        Generate a simple response without context/prompt templating.
        Used for selection tasks, structured output, etc.
        """
        try:
            # Ensure client is initialized
            self._initialize_client()
            
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

            # Default: Ollama
            response = await self.http_client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temperature for structured output
                        "top_p": 0.9,
                        "max_tokens": 200
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
            logger.error(f"Error generating simple LLM response: {e}")
            return "I couldn't generate a response due to an error."
    
    def _build_prompt(self, query: str, context: str) -> str:
        """Build the prompt for the LLM"""
        return f"""You are a helpful AI assistant that answers questions based on the provided document context.

Each document is labeled with its filename in the format [Document: filename.ext].

Context information:
{context}

Question: {query}

Instructions:
- Answer based on the DOCUMENT CONTENT, not just filenames
- Read the actual text in each document to understand what it contains
- When listing documents, look for mentions in the CONTENT (e.g., if content says "delivery receipt", include it)
- Include the [Document: filename] label when referencing documents in your answer
- If the information is not in the context, say "I don't have information about that in the current documents"
- Be thorough - check all provided documents carefully
- Use specific details and quotes from the content when relevant

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
