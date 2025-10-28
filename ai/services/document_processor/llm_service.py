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
                        "max_output_tokens": 1024,
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
    
    def _build_prompt(self, query: str, context: str) -> str:
        """Build the prompt for the LLM"""
        return f"""You are a helpful AI assistant that answers questions based on the provided document context.

Context information:
{context}

Question: {query}

Instructions:
- Answer the question directly and clearly based on the provided context
- If the information is not in the context, say "I don't have information about that in the current documents"
- Be concise but comprehensive
- Use specific details from the context when relevant
- If you're uncertain, acknowledge it

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
