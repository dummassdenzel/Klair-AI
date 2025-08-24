import logging
from pathlib import Path
from typing import Optional
import asyncio

logger = logging.getLogger(__name__)


class TextExtractor:
    """Service for extracting text from various document formats"""
    
    def __init__(self):
        self.supported_extensions = {".pdf", ".docx", ".txt"}
    
    async def extract_text_async(self, file_path: str) -> str:
        """Extract text asynchronously to avoid blocking"""
        def sync_extract():
            return self._extract_text_sync(file_path)
        
        # Run in thread pool for CPU-intensive operations
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, sync_extract)
    
    def _extract_text_sync(self, file_path: str) -> str:
        """Synchronous text extraction with better error handling"""
        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()
        
        try:
            if ext == ".pdf":
                return self._extract_pdf(file_path)
            elif ext == ".docx":
                return self._extract_docx(file_path)
            elif ext == ".txt":
                return self._extract_txt(file_path)
            else:
                raise ValueError(f"Unsupported file type: {ext}")
        except Exception as e:
            logger.error(f"Text extraction failed for {file_path}: {e}")
            raise
    
    def _extract_pdf(self, file_path: str) -> str:
        """Extract text from PDF"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except Exception as e:
            logger.error(f"PDF extraction failed for {file_path}: {e}")
            raise
    
    def _extract_docx(self, file_path: str) -> str:
        """Extract text from DOCX"""
        try:
            import docx
            doc = docx.Document(file_path)
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            logger.error(f"DOCX extraction failed for {file_path}: {e}")
            raise
    
    def _extract_txt(self, file_path: str) -> str:
        """Extract text from TXT with encoding detection"""
        try:
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            for encoding in encodings:
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            
            # Fallback with error handling
            with open(file_path, "r", encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.error(f"TXT extraction failed for {file_path}: {e}")
            raise
    
    def is_supported_file(self, file_path: str) -> bool:
        """Check if file type is supported"""
        return Path(file_path).suffix.lower() in self.supported_extensions
