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

settings = Settings()
