"""Unified configuration — single source of truth for the entire application."""

import os
from dotenv import load_dotenv
from typing import List, Dict, Any

load_dotenv()


class Settings:
    # Database (SQLite — zero setup for desktop use)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./klair.db")

    # ChromaDB / embeddings
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR") or os.getenv("CHROMA_PERSIST_DIRECTORY", "./chroma_db")
    EMBED_MODEL_NAME: str = os.getenv("EMBED_MODEL_NAME") or os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    # Chunking
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))

    # File processing
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "10"))
    SUPPORTED_EXTENSIONS: List[str] = os.getenv("SUPPORTED_EXTENSIONS", ".pdf,.docx,.txt,.xlsx,.xls,.pptx").split(",")

    # LLM (set LLM_PROVIDER to switch: ollama | gemini | groq)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
    LLM_MAX_RESPONSE_TOKENS: int = int(os.getenv("LLM_MAX_RESPONSE_TOKENS", "8192"))
    # Ollama (local)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "tinyllama")
    OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "120"))
    # Gemini (Google)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    # Groq — defaults tuned for 30k TPM tier
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    GROQ_MAX_CONTEXT_CHARS: int = int(os.getenv("GROQ_MAX_CONTEXT_CHARS", "50000"))
    GROQ_MAX_SIMPLE_PROMPT_CHARS: int = int(os.getenv("GROQ_MAX_SIMPLE_PROMPT_CHARS", "15000"))
    GROQ_MAX_LISTING_CONTEXT_CHARS: int = int(os.getenv("GROQ_MAX_LISTING_CONTEXT_CHARS", "25000"))

    # PPTX Preview
    LIBREOFFICE_PATH: str = os.getenv("LIBREOFFICE_PATH", "")
    PPTX_CACHE_DIR: str = os.getenv("PPTX_CACHE_DIR", "./pptx_cache")
    PPTX_CACHE_ENABLED: bool = os.getenv("PPTX_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
    PPTX_CONVERSION_TIMEOUT: int = int(os.getenv("PPTX_CONVERSION_TIMEOUT", "60"))

    # OCR
    TESSERACT_PATH: str = os.getenv("TESSERACT_PATH", "")
    OCR_CACHE_DIR: str = os.getenv("OCR_CACHE_DIR", "./ocr_cache")
    OCR_CACHE_ENABLED: bool = os.getenv("OCR_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
    OCR_LANGUAGES: str = os.getenv("OCR_LANGUAGES", "eng")
    OCR_TIMEOUT: int = int(os.getenv("OCR_TIMEOUT", "300"))

    # Directory initialization timeout (seconds)
    INITIALIZE_DIRECTORY_TIMEOUT: int = int(os.getenv("INITIALIZE_DIRECTORY_TIMEOUT", "600"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "human")
    LOG_FILE: str = os.getenv("LOG_FILE", "")
    SQLALCHEMY_ECHO: bool = os.getenv("SQLALCHEMY_ECHO", "false").lower() in ("1", "true", "yes")

    # ── helpers ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serializable snapshot of document-processor-related settings."""
        return {
            "persist_dir": self.CHROMA_PERSIST_DIR,
            "embed_model_name": self.EMBED_MODEL_NAME,
            "max_file_size_mb": self.MAX_FILE_SIZE_MB,
            "chunk_size": self.CHUNK_SIZE,
            "chunk_overlap": self.CHUNK_OVERLAP,
            "ollama_base_url": self.OLLAMA_BASE_URL,
            "ollama_model": self.OLLAMA_MODEL,
            "batch_size": self.BATCH_SIZE,
            "supported_extensions": self.SUPPORTED_EXTENSIONS,
        }

    _UPDATABLE = {"chunk_size", "chunk_overlap", "max_file_size_mb", "ollama_model", "ollama_base_url"}

    def update(self, **kwargs) -> None:
        """Update allowlisted settings at runtime (e.g. from /api/update-configuration)."""
        mapping = {
            "chunk_size": "CHUNK_SIZE",
            "chunk_overlap": "CHUNK_OVERLAP",
            "max_file_size_mb": "MAX_FILE_SIZE_MB",
            "ollama_model": "OLLAMA_MODEL",
            "ollama_base_url": "OLLAMA_BASE_URL",
        }
        for key, value in kwargs.items():
            attr = mapping.get(key)
            if attr:
                setattr(self, attr, value)


settings = Settings()