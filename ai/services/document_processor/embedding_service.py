import logging
from typing import List
import numpy as np


logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for managing document embeddings"""
    
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self.embed_model = None
        # Don't initialize model immediately - use lazy loading
    
    def _initialize_model(self):
        """Initialize the embedding model (lazy loading)"""
        if self.embed_model is not None:
            return  # Already initialized
        
        try:
            # Import here to avoid startup issues
            from sentence_transformers import SentenceTransformer
            
            logger.info(f"Loading embedding model: {self.model_name}")
            self.embed_model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    
    def encode_texts(self, texts: List[str]) -> List[List[float]]:
        """Encode a list of texts to embeddings"""
        if not texts:
            return []
        
        try:
            # Initialize model if needed
            self._initialize_model()
            
            if not self.embed_model:
                raise RuntimeError("Embedding model not initialized")
            
            # Convert to numpy array for batch processing
            embeddings = self.embed_model.encode(texts)
            
            # Convert to list of lists
            if isinstance(embeddings, np.ndarray):
                return embeddings.tolist()
            return embeddings
            
        except Exception as e:
            logger.error(f"Error encoding texts: {e}")
            raise
    
    def encode_single_text(self, text: str) -> List[float]:
        """Encode a single text to embedding"""
        return self.encode_texts([text])[0]
    
    def get_embedding_dimension(self) -> int:
        """Get the dimension of embeddings"""
        try:
            # Initialize model if needed
            self._initialize_model()
            
            if not self.embed_model:
                return 0
            return self.embed_model.get_sentence_embedding_dimension()
        except Exception as e:
            logger.error(f"Error getting embedding dimension: {e}")
            return 0
    
    def reload_model(self, model_name: str = None):
        """Reload the embedding model"""
        if model_name:
            self.model_name = model_name
        
        # Clear existing model
        if self.embed_model:
            del self.embed_model
            self.embed_model = None
        
        # Reinitialize
        self._initialize_model()
    
    def cleanup(self):
        """Cleanup resources"""
        if self.embed_model:
            del self.embed_model
            self.embed_model = None
