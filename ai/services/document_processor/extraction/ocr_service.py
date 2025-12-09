"""
OCR Service for Extracting Text from Scanned Documents

Uses Tesseract OCR to extract text from:
- Scanned PDFs (image-based PDFs)
- Image files (JPG, PNG, TIFF, BMP)

Includes caching to avoid re-OCR of unchanged files.
"""

import logging
import hashlib
import os
import platform
import shutil
from pathlib import Path
from typing import Optional, List
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class OCRService:
    """Service for OCR text extraction from scanned documents and images"""
    
    def __init__(
        self,
        tesseract_path: Optional[str] = None,
        cache_dir: str = "./ocr_cache",
        languages: str = "eng"
    ):
        """
        Initialize OCR service.
        
        Args:
            tesseract_path: Path to Tesseract executable. If None, will auto-detect.
            cache_dir: Directory to store cached OCR results
            languages: Comma-separated language codes (e.g., "eng,spa,fra")
        """
        self.tesseract_path = tesseract_path or self._detect_tesseract()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.languages = languages
        
        # OCR timeout (seconds) - longer for large images
        self.ocr_timeout = 300  # 5 minutes
        
        # Supported image formats
        self.supported_image_extensions = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
        
        if not self.tesseract_path:
            logger.warning("Tesseract OCR not found. OCR functionality will not be available.")
        else:
            logger.info(f"OCR Service initialized with Tesseract: {self.tesseract_path} (languages: {languages})")
    
    def _detect_tesseract(self) -> Optional[str]:
        """
        Auto-detect Tesseract installation path.
        
        Returns:
            Path to Tesseract executable, or None if not found
        """
        system = platform.system()
        
        # Common installation paths
        if system == "Windows":
            possible_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
            ]
            # Also check PATH
            if shutil.which("tesseract.exe"):
                return "tesseract.exe"
        elif system == "Darwin":  # macOS
            possible_paths = [
                "/usr/local/bin/tesseract",
                "/opt/homebrew/bin/tesseract",
                "/usr/bin/tesseract",
            ]
            if shutil.which("tesseract"):
                return "tesseract"
        else:  # Linux
            possible_paths = [
                "/usr/bin/tesseract",
                "/usr/local/bin/tesseract",
            ]
            if shutil.which("tesseract"):
                return "tesseract"
        
        # Check possible paths
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                logger.info(f"Found Tesseract at: {path}")
                return path
        
        logger.warning("Tesseract not found in common locations")
        return None
    
    def is_available(self) -> bool:
        """Check if Tesseract OCR is available"""
        return self.tesseract_path is not None and os.path.exists(self.tesseract_path)
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file for cache key"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read file in chunks to handle large files
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _get_cache_path(self, file_path: str) -> Path:
        """Get cache file path for an OCR result"""
        file_hash = self._calculate_file_hash(file_path)
        return self.cache_dir / f"{file_hash}.txt"
    
    def _is_cache_valid(self, file_path: str, cache_path: Path) -> bool:
        """
        Check if cached OCR result is still valid.
        
        Cache is valid if:
        1. Cache file exists
        2. Source file hasn't been modified since cache was created
        """
        if not cache_path.exists():
            return False
        
        try:
            file_mtime = os.path.getmtime(file_path)
            cache_mtime = os.path.getmtime(cache_path)
            
            # Cache is valid if it's newer than the source file
            return cache_mtime >= file_mtime
        except OSError:
            return False
    
    def detect_scanned_pdf(self, pdf_path: str) -> bool:
        """
        Detect if PDF is scanned (image-based) by checking if it has extractable text.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            True if PDF appears to be scanned (no extractable text), False otherwise
        """
        try:
            import fitz  # PyMuPDF
            
            doc = fitz.open(pdf_path)
            total_text_length = 0
            total_pages = len(doc)
            
            if total_pages == 0:
                doc.close()
                return True  # Empty PDF, treat as scanned
            
            # Check text extraction on each page
            for page in doc:
                text = page.get_text()
                total_text_length += len(text.strip())
            
            doc.close()
            
            # If average text per page < threshold, likely scanned
            avg_text_per_page = total_text_length / total_pages if total_pages > 0 else 0
            threshold = 50  # Characters per page threshold
            
            is_scanned = avg_text_per_page < threshold
            
            if is_scanned:
                logger.info(f"PDF detected as scanned: {pdf_path} (avg {avg_text_per_page:.1f} chars/page)")
            else:
                logger.debug(f"PDF has extractable text: {pdf_path} (avg {avg_text_per_page:.1f} chars/page)")
            
            return is_scanned
            
        except Exception as e:
            logger.warning(f"Error detecting scanned PDF {pdf_path}: {e}, assuming scanned")
            return True  # If detection fails, assume scanned to be safe
    
    def _extract_text_from_image_sync(self, image_path: str, use_cache: bool = True) -> str:
        """
        Synchronously extract text from an image file using Tesseract OCR.
        
        Args:
            image_path: Path to image file
            use_cache: Whether to use cached result if available
            
        Returns:
            Extracted text from image
        """
        if not self.is_available():
            raise RuntimeError("Tesseract OCR not available. Please install Tesseract to enable OCR functionality.")
        
        image_path_obj = Path(image_path)
        if not image_path_obj.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        # Check cache first
        if use_cache:
            cache_path = self._get_cache_path(image_path)
            if self._is_cache_valid(image_path, cache_path):
                logger.info(f"Using cached OCR result for {image_path_obj.name}")
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception as e:
                    logger.warning(f"Failed to read cache file {cache_path}: {e}, re-running OCR")
        
        # Perform OCR
        try:
            import pytesseract
            from PIL import Image
            
            # Set Tesseract path if specified
            if self.tesseract_path and self.tesseract_path != "tesseract" and self.tesseract_path != "tesseract.exe":
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_path
            
            # Open and process image
            image = Image.open(image_path)
            
            # Perform OCR with specified languages
            logger.info(f"Running OCR on {image_path_obj.name} (languages: {self.languages})...")
            text = pytesseract.image_to_string(image, lang=self.languages)
            
            # Clean up extracted text
            text = text.strip()
            
            if not text:
                logger.warning(f"No text extracted from {image_path_obj.name}")
                return ""
            
            # Cache the result
            if use_cache:
                cache_path = self._get_cache_path(image_path)
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                    logger.debug(f"Cached OCR result for {image_path_obj.name}")
                except Exception as e:
                    logger.warning(f"Failed to cache OCR result: {e}")
            
            logger.info(f"OCR complete for {image_path_obj.name}: {len(text)} characters extracted")
            return text
            
        except ImportError:
            raise RuntimeError(
                "OCR dependencies not installed. Please install: pip install pytesseract Pillow"
            )
        except Exception as e:
            logger.error(f"OCR extraction failed for {image_path}: {e}")
            raise RuntimeError(f"OCR extraction failed: {str(e)}")
    
    def _extract_text_from_scanned_pdf_sync(self, pdf_path: str, use_cache: bool = True) -> str:
        """
        Synchronously extract text from a scanned PDF by converting pages to images and OCRing.
        
        Args:
            pdf_path: Path to PDF file
            use_cache: Whether to use cached result if available
            
        Returns:
            Extracted text from all pages
        """
        if not self.is_available():
            raise RuntimeError("Tesseract OCR not available. Please install Tesseract to enable OCR functionality.")
        
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        # Check cache first
        if use_cache:
            cache_path = self._get_cache_path(pdf_path)
            if self._is_cache_valid(pdf_path, cache_path):
                logger.info(f"Using cached OCR result for {pdf_path_obj.name}")
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception as e:
                    logger.warning(f"Failed to read cache file {cache_path}: {e}, re-running OCR")
        
        # Convert PDF pages to images and OCR each page
        try:
            import fitz  # PyMuPDF
            import pytesseract
            from PIL import Image
            import io
            
            # Set Tesseract path if specified
            if self.tesseract_path and self.tesseract_path != "tesseract" and self.tesseract_path != "tesseract.exe":
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_path
            
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            
            if total_pages == 0:
                doc.close()
                return ""
            
            logger.info(f"Processing {total_pages} pages from scanned PDF: {pdf_path_obj.name}")
            
            all_text_parts = []
            
            for page_num in range(total_pages):
                page = doc[page_num]
                
                # Convert page to image (300 DPI for good OCR quality)
                mat = fitz.Matrix(300/72, 300/72)  # 300 DPI
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to PIL Image
                img_data = pix.tobytes("png")
                image = Image.open(io.BytesIO(img_data))
                
                # Perform OCR on this page
                logger.debug(f"OCR page {page_num + 1}/{total_pages}...")
                page_text = pytesseract.image_to_string(image, lang=self.languages)
                
                if page_text.strip():
                    all_text_parts.append(f"Page {page_num + 1}:\n{page_text.strip()}")
                
                pix = None  # Free memory
            
            doc.close()
            
            # Combine all pages
            text = "\n\n".join(all_text_parts)
            text = text.strip()
            
            if not text:
                logger.warning(f"No text extracted from scanned PDF {pdf_path_obj.name}")
                return ""
            
            # Cache the result
            if use_cache:
                cache_path = self._get_cache_path(pdf_path)
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                    logger.debug(f"Cached OCR result for {pdf_path_obj.name}")
                except Exception as e:
                    logger.warning(f"Failed to cache OCR result: {e}")
            
            logger.info(f"OCR complete for {pdf_path_obj.name}: {len(text)} characters extracted from {total_pages} pages")
            return text
            
        except ImportError:
            raise RuntimeError(
                "OCR dependencies not installed. Please install: pip install pytesseract Pillow"
            )
        except Exception as e:
            logger.error(f"OCR extraction failed for scanned PDF {pdf_path}: {e}")
            raise RuntimeError(f"OCR extraction failed: {str(e)}")
    
    async def extract_text_from_image(self, image_path: str, use_cache: bool = True) -> str:
        """
        Asynchronously extract text from an image file.
        
        Args:
            image_path: Path to image file
            use_cache: Whether to use cached result if available
            
        Returns:
            Extracted text from image
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._extract_text_from_image_sync,
            image_path,
            use_cache
        )
    
    async def extract_text_from_scanned_pdf(self, pdf_path: str, use_cache: bool = True) -> str:
        """
        Asynchronously extract text from a scanned PDF.
        
        Args:
            pdf_path: Path to PDF file
            use_cache: Whether to use cached result if available
            
        Returns:
            Extracted text from all pages
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._extract_text_from_scanned_pdf_sync,
            pdf_path,
            use_cache
        )
    
    def get_cached_text(self, file_path: str) -> Optional[str]:
        """
        Get cached OCR text if available and valid.
        
        Args:
            file_path: Path to file
            
        Returns:
            Cached text, or None if not available/invalid
        """
        cache_path = self._get_cache_path(file_path)
        if self._is_cache_valid(file_path, cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                return None
        return None
    
    def is_image_file(self, file_path: str) -> bool:
        """Check if file is a supported image format"""
        return Path(file_path).suffix.lower() in self.supported_image_extensions

