"""Unified configuration — single source of truth for the entire application."""

from typing import List, Dict, Any
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database (SQLite — zero setup for desktop use)
    DATABASE_URL: str = "sqlite+aiosqlite:///./klair.db"

    # ChromaDB / embeddings
    # CHROMA_PERSIST_DIRECTORY is accepted as a legacy alias.
    CHROMA_PERSIST_DIR: str = Field(
        default="./chroma_db",
        validation_alias=AliasChoices("CHROMA_PERSIST_DIR", "CHROMA_PERSIST_DIRECTORY"),
    )
    # bge-base-en-v1.5 (109M params, 768-dim) replaces the former bge-small-en-v1.5 (33M, 384-dim).
    # Both models share the same 512-token context window and identical Python API, so chunking
    # config and call sites are unchanged. The upgrade improves domain vocabulary coverage and
    # cosine-similarity spread, which feeds directly into RRF fusion quality.
    # After changing this value you MUST delete the ChromaDB directory and BM25 index, then
    # re-index all documents (see docs/AI_QUALITY_AUDIT.md — Phase 2 Re-indexing Note).
    # EMBEDDING_MODEL is accepted as a legacy alias.
    EMBED_MODEL_NAME: str = Field(
        default="BAAI/bge-base-en-v1.5",
        validation_alias=AliasChoices("EMBED_MODEL_NAME", "EMBEDDING_MODEL"),
    )

    # Chunking — values are in TOKENS, not characters.
    # Both bge-base and bge-small share a 512-token context window; keep CHUNK_SIZE <= MAX_CHUNK_TOKENS.
    # Rule of thumb: 1 token ≈ 4 English characters.
    CHUNK_SIZE: int = 300           # tokens per chunk
    CHUNK_OVERLAP: int = 50         # overlap in tokens
    MAX_CHUNK_TOKENS: int = 512     # hard cap = embedding model max

    # File processing
    MAX_FILE_SIZE_MB: int = 50
    BATCH_SIZE: int = 10
    # Stored as a comma-separated string so env-var parsing stays simple.
    # Use get_supported_extensions() for the list form.
    SUPPORTED_EXTENSIONS: str = ".pdf,.docx,.txt,.xlsx,.xls,.pptx"

    def get_supported_extensions(self) -> List[str]:
        return [e.strip() for e in self.SUPPORTED_EXTENSIONS.split(",") if e.strip()]

    # Context Compression
    # Off by default: compression calls the LLM once *per retrieved chunk* (in parallel),
    # adding significant latency on Ollama and wasting API tokens on Groq/Gemini for
    # most queries. Enable it only for deployments where context regularly exceeds the
    # LLM's context window and a fast provider is in use.
    CONTEXT_COMPRESSION_ENABLED: bool = False
    # Minimum total retrieved-context size (chars) before compression is even attempted.
    # At the default of 8 000 chars ≈ 2 000 tokens — well above chunk noise but below
    # typical 4 k-token Ollama windows. Raise this for large-context cloud models.
    CONTEXT_COMPRESSION_MIN_CHARS: int = 8000

    # LLM (set LLM_PROVIDER to switch: ollama | gemini | groq)
    LLM_PROVIDER: str = "ollama"
    LLM_MAX_RESPONSE_TOKENS: int = 8192
    # RAG generation temperature (0.0 = fully deterministic, 1.0 = fully creative).
    # Default 0.1: low temperature keeps factual document answers consistent and reproducible.
    # Planner / classifier calls always use 0.1 regardless of this setting.
    LLM_TEMPERATURE: float = 0.1
    # Ollama (local)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "tinyllama"
    OLLAMA_TIMEOUT: int = 120
    # Gemini (Google)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-pro"
    # Groq — defaults tuned for 30k TPM tier
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    GROQ_MAX_CONTEXT_CHARS: int = 50000
    GROQ_MAX_SIMPLE_PROMPT_CHARS: int = 15000
    GROQ_MAX_LISTING_CONTEXT_CHARS: int = 25000
    # OpenAI (ChatGPT)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    # Anthropic (Claude)
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    # xAI (Grok)
    XAI_API_KEY: str = ""
    XAI_MODEL: str = "grok-3-mini"

    # PPTX Preview
    LIBREOFFICE_PATH: str = ""
    PPTX_CACHE_DIR: str = "./preview_cache"
    PPTX_CACHE_ENABLED: bool = True
    PPTX_CONVERSION_TIMEOUT: int = 60

    # OCR
    TESSERACT_PATH: str = ""
    OCR_CACHE_DIR: str = "./ocr_cache"
    OCR_CACHE_ENABLED: bool = True
    OCR_LANGUAGES: str = "eng"
    OCR_TIMEOUT: int = 300

    # Directory initialization timeout (seconds)
    INITIALIZE_DIRECTORY_TIMEOUT: int = 600

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "human"
    LOG_FILE: str = ""
    SQLALCHEMY_ECHO: bool = False

    # When true, POST /api/debug/retrieval-inspect exposes retrieved context and RAG prompt preview.
    # Off by default: can leak indexed document text to anyone who can reach the API.
    RETRIEVAL_INSPECT_ENABLED: bool = False

    # ── helpers ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serializable snapshot of document-processor-related settings."""
        return {
            "persist_dir": self.CHROMA_PERSIST_DIR,
            "embed_model_name": self.EMBED_MODEL_NAME,
            "max_file_size_mb": self.MAX_FILE_SIZE_MB,
            "chunk_size": self.CHUNK_SIZE,
            "chunk_overlap": self.CHUNK_OVERLAP,
            "max_chunk_tokens": self.MAX_CHUNK_TOKENS,
            "ollama_base_url": self.OLLAMA_BASE_URL,
            "ollama_model": self.OLLAMA_MODEL,
            "batch_size": self.BATCH_SIZE,
            "supported_extensions": self.get_supported_extensions(),
        }

    _UPDATABLE = {
        "chunk_size", "chunk_overlap", "max_file_size_mb",
        "llm_provider", "llm_temperature",
        "ollama_model", "ollama_base_url",
        "gemini_model", "gemini_api_key",
        "groq_model", "groq_api_key",
        "openai_model", "openai_api_key",
        "anthropic_model", "anthropic_api_key",
        "xai_model", "xai_api_key",
    }

    def update(self, **kwargs) -> None:
        """Update allowlisted settings at runtime (e.g. from /api/update-configuration)."""
        mapping = {
            "chunk_size": "CHUNK_SIZE",
            "chunk_overlap": "CHUNK_OVERLAP",
            "max_file_size_mb": "MAX_FILE_SIZE_MB",
            "llm_provider": "LLM_PROVIDER",
            "llm_temperature": "LLM_TEMPERATURE",
            "ollama_model": "OLLAMA_MODEL",
            "ollama_base_url": "OLLAMA_BASE_URL",
            "gemini_model": "GEMINI_MODEL",
            "gemini_api_key": "GEMINI_API_KEY",
            "groq_model": "GROQ_MODEL",
            "groq_api_key": "GROQ_API_KEY",
            "openai_model": "OPENAI_MODEL",
            "openai_api_key": "OPENAI_API_KEY",
            "anthropic_model": "ANTHROPIC_MODEL",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "xai_model": "XAI_MODEL",
            "xai_api_key": "XAI_API_KEY",
        }
        for key, value in kwargs.items():
            attr = mapping.get(key)
            if attr:
                setattr(self, attr, type(getattr(self, attr))(value))


settings = Settings()
