import logging
import threading
from typing import List
import numpy as np


logger = logging.getLogger(__name__)

# BGE models use asymmetric encoding: queries require this prefix; documents do not.
# See https://huggingface.co/BAAI/bge-base-en-v1.5#model-list
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingService:
    """Service for managing document embeddings"""
    
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self.embed_model = None
        self._init_lock = threading.Lock()
        # Don't initialize model immediately - use lazy loading
    
    def _initialize_model(self):
        """Initialize the embedding model (lazy loading)"""
        if self.embed_model is not None:
            return  # Already initialized
        # Guard against concurrent initialization (background index + query warmup)
        # which can trigger torch meta-tensor transfer errors.
        with self._init_lock:
            if self.embed_model is not None:
                return
        
            try:
                # Import here to avoid startup issues
                from sentence_transformers import SentenceTransformer
                
                logger.info(f"Loading embedding model: {self.model_name}")
                # Force CPU to avoid device auto-detection edge cases on Windows
                # that can surface as meta-tensor transfer errors in some torch builds.
                self.embed_model = SentenceTransformer(self.model_name, device="cpu")
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load embedding model: {e}")
                raise
    
    # Conservative character cap before passing text to the embedding model.
    # BGE-base max is 512 tokens; dense / garbled OCR text can produce > 512
    # tokens from < 2 000 characters.  Capping here prevents the transformers
    # "Token indices sequence length is longer than the specified maximum
    # sequence length" warning and ensures the chunker's trim result is
    # faithfully respected after the decode → re-encode round-trip.
    _MAX_EMBED_CHARS = 1800

    def encode_texts(self, texts: List[str]) -> List[List[float]]:
        """Encode a list of texts to embeddings"""
        if not texts:
            return []
        
        try:
            # Initialize model if needed
            self._initialize_model()
            
            if not self.embed_model:
                raise RuntimeError("Embedding model not initialized")

            # Hard-cap each text to prevent the embedding model from receiving
            # sequences that exceed its positional-encoding window (512 tokens).
            safe_texts = [
                t[: self._MAX_EMBED_CHARS] if len(t) > self._MAX_EMBED_CHARS else t
                for t in texts
            ]
            
            # Convert to numpy array for batch processing
            embeddings = self.embed_model.encode(safe_texts, show_progress_bar=False)
            
            # Convert to list of lists
            if isinstance(embeddings, np.ndarray):
                return embeddings.tolist()
            return embeddings
            
        except Exception as e:
            logger.error(f"Error encoding texts: {e}")
            raise
    
    def encode_single_text(self, text: str) -> List[float]:
        """Encode a single document text to embedding (no prefix)."""
        return self.encode_texts([text])[0]

    def encode_query(self, text: str) -> List[float]:
        """Encode a search query.

        BGE models require the asymmetric query prefix for queries so that
        query vectors align with document vectors in the shared embedding space.
        Non-BGE models receive the raw text unchanged.
        """
        prefixed = (BGE_QUERY_PREFIX + text) if "bge" in self.model_name.lower() else text
        return self.encode_single_text(prefixed)

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
    
    def get_tokenizer(self):
        """
        Return the underlying HuggingFace tokenizer from the loaded SentenceTransformer.
        Triggers lazy model initialization if the model has not been loaded yet.
        Returns None if the model does not expose a tokenizer attribute.
        """
        try:
            self._initialize_model()
            return getattr(self.embed_model, "tokenizer", None)
        except Exception as e:
            logger.warning("Could not retrieve tokenizer from embedding model: %s", e)
            return None

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
