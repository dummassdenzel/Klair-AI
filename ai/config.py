# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    CHROMA_PERSIST_DIRECTORY: str = os.getenv("CHROMA_PERSIST_DIRECTORY")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL")
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB"))
    SUPPORTED_EXTENSIONS: list = os.getenv("SUPPORTED_EXTENSIONS").split(',')

    # Ollama settings
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "tinyllama")
    OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "120"))
    
    # Embedding model
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

settings = Settings()
