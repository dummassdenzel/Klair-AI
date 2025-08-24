import logging
from typing import Optional


logger = logging.getLogger(__name__)


class LLMService:
    """Service for managing LLM interactions"""
    
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model
        self.http_client = None
        # Don't initialize immediately - use lazy loading
    
    def _initialize_client(self):
        """Initialize HTTP client for Ollama (lazy loading)"""
        if self.http_client is not None:
            return  # Already initialized
        
        try:
            # Import here to avoid startup issues
            import httpx
            
            self.http_client = httpx.AsyncClient(timeout=30.0)
            logger.info(f"LLM service initialized with model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM service: {e}")
            raise
    
    async def generate_response(self, query: str, context: str) -> str:
        """Generate response using Ollama LLM"""
        try:
            # Initialize client if needed
            self._initialize_client()
            
            prompt = self._build_prompt(query, context)
            
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
        except Exception as e:
            logger.error(f"Error during LLM service cleanup: {e}")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
