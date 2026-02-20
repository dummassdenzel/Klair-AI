# Unified configuration for the entire application
import os
from dotenv import load_dotenv
from typing import List

load_dotenv()

class Settings:
    # Database settings (SQLite by default — zero setup for desktop use)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./klair.db")
    
    # Document processor settings (from your new config)
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR") or os.getenv("CHROMA_PERSIST_DIRECTORY", "./chroma_db")
    EMBED_MODEL_NAME: str = os.getenv("EMBED_MODEL_NAME") or os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    
    # LLM settings (set LLM_PROVIDER to switch: ollama | gemini | groq)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
    LLM_MAX_RESPONSE_TOKENS: int = int(os.getenv("LLM_MAX_RESPONSE_TOKENS", "8192"))
    # Ollama (local)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "tinyllama")
    OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "120"))
    # Gemini (Google)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    # Groq (https://console.groq.com). Default model: 30k TPM tier; adjust limits if you use a lower-TPM model.
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    # Input limits (chars). Defaults tuned for 30k TPM; lower these if you hit 413 on a different tier.
    GROQ_MAX_CONTEXT_CHARS: int = int(os.getenv("GROQ_MAX_CONTEXT_CHARS", "50000"))
    GROQ_MAX_SIMPLE_PROMPT_CHARS: int = int(os.getenv("GROQ_MAX_SIMPLE_PROMPT_CHARS", "15000"))
    GROQ_MAX_LISTING_CONTEXT_CHARS: int = int(os.getenv("GROQ_MAX_LISTING_CONTEXT_CHARS", "25000"))
    
    # File processing
    SUPPORTED_EXTENSIONS: List[str] = os.getenv("SUPPORTED_EXTENSIONS", ".pdf,.docx,.txt,.xlsx,.xls,.pptx").split(',')
    
    # PPTX Preview settings
    LIBREOFFICE_PATH: str = os.getenv("LIBREOFFICE_PATH", "")  # Auto-detect if empty
    PPTX_CACHE_DIR: str = os.getenv("PPTX_CACHE_DIR", "./pptx_cache")
    PPTX_CACHE_ENABLED: bool = os.getenv("PPTX_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
    PPTX_CONVERSION_TIMEOUT: int = int(os.getenv("PPTX_CONVERSION_TIMEOUT", "60"))
    
    # OCR settings
    TESSERACT_PATH: str = os.getenv("TESSERACT_PATH", "")  # Auto-detect if empty
    OCR_CACHE_DIR: str = os.getenv("OCR_CACHE_DIR", "./ocr_cache")
    OCR_CACHE_ENABLED: bool = os.getenv("OCR_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
    OCR_LANGUAGES: str = os.getenv("OCR_LANGUAGES", "eng")  # Comma-separated: "eng,spa,fra"
    OCR_TIMEOUT: int = int(os.getenv("OCR_TIMEOUT", "300"))  # 5 minutes for large images

    # Directory initialization (set-directory) max time before 504
    INITIALIZE_DIRECTORY_TIMEOUT: int = int(os.getenv("INITIALIZE_DIRECTORY_TIMEOUT", "600"))  # 10 minutes

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "human")  # 'json' or 'human'
    LOG_FILE: str = os.getenv("LOG_FILE", "")  # Optional log file path
    SQLALCHEMY_ECHO: bool = os.getenv("SQLALCHEMY_ECHO", "false").lower() in ("1", "true", "yes")

settings = Settings()