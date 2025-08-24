"""
Configuration for Document Processor Services
"""

import os
from typing import Dict, Any
from dataclasses import dataclass

# Import the unified settings
from config import settings

@dataclass
class DocumentProcessorConfig:
    """Configuration for document processor services"""
    
    # ChromaDB settings
    persist_dir: str = settings.CHROMA_PERSIST_DIR
    
    # Embedding settings
    embed_model_name: str = settings.EMBED_MODEL_NAME
    
    # File processing settings
    max_file_size_mb: int = settings.MAX_FILE_SIZE_MB
    chunk_size: int = settings.CHUNK_SIZE
    chunk_overlap: int = settings.CHUNK_OVERLAP
    
    # LLM settings
    ollama_base_url: str = settings.OLLAMA_BASE_URL
    ollama_model: str = settings.OLLAMA_MODEL
    
    # Processing settings
    batch_size: int = 10
    max_concurrent_files: int = 5
    
    # Supported file types
    supported_extensions: set = None
    
    def __post_init__(self):
        if self.supported_extensions is None:
            self.supported_extensions = set(settings.SUPPORTED_EXTENSIONS)
    
    @classmethod
    def from_environment(cls) -> 'DocumentProcessorConfig':
        """Create configuration from environment variables"""
        return cls(
            persist_dir=os.getenv("CHROMA_PERSIST_DIR", settings.CHROMA_PERSIST_DIR),
            embed_model_name=os.getenv("EMBED_MODEL_NAME", settings.EMBED_MODEL_NAME),
            max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", str(settings.MAX_FILE_SIZE_MB))),
            chunk_size=int(os.getenv("CHUNK_SIZE", str(settings.CHUNK_SIZE))),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", str(settings.CHUNK_OVERLAP))),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", settings.OLLAMA_BASE_URL),
            ollama_model=os.getenv("OLLAMA_MODEL", settings.OLLAMA_MODEL),
            batch_size=int(os.getenv("BATCH_SIZE", "10")),
            max_concurrent_files=int(os.getenv("MAX_CONCURRENT_FILES", "5"))
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return {
            "persist_dir": self.persist_dir,
            "embed_model_name": self.embed_model_name,
            "max_file_size_mb": self.max_file_size_mb,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "batch_size": self.batch_size,
            "max_concurrent_files": self.max_concurrent_files,
            "supported_extensions": list(self.supported_extensions)
        }
    
    def update(self, **kwargs):
        """Update configuration with new values"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

# Default configuration
default_config = DocumentProcessorConfig()

# Environment-based configuration
config = DocumentProcessorConfig.from_environment()