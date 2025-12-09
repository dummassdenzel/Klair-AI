"""
PPTX to PDF Converter Service

Converts PowerPoint files to PDF using LibreOffice headless mode.
Includes caching to avoid re-conversion of unchanged files.
"""

import logging
import subprocess
import shutil
import hashlib
import os
import platform
from pathlib import Path
from typing import Optional
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class PPTXConverter:
    """Service for converting PPTX files to PDF using LibreOffice"""
    
    def __init__(self, libreoffice_path: Optional[str] = None, cache_dir: str = "./pptx_cache"):
        """
        Initialize PPTX converter.
        
        Args:
            libreoffice_path: Path to LibreOffice executable. If None, will auto-detect.
            cache_dir: Directory to store cached PDF conversions
        """
        self.libreoffice_path = libreoffice_path or self._detect_libreoffice()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Conversion timeout (seconds)
        self.conversion_timeout = 60
        
        if not self.libreoffice_path:
            logger.warning("LibreOffice not found. PPTX preview will not work.")
        else:
            logger.info(f"PPTX Converter initialized with LibreOffice: {self.libreoffice_path}")
    
    def _detect_libreoffice(self) -> Optional[str]:
        """
        Auto-detect LibreOffice installation path.
        
        Returns:
            Path to LibreOffice executable, or None if not found
        """
        system = platform.system()
        
        # Common installation paths
        if system == "Windows":
            possible_paths = [
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                os.path.expanduser(r"~\AppData\Local\Programs\LibreOffice\program\soffice.exe"),
            ]
            # Also check PATH
            if shutil.which("soffice.exe"):
                return "soffice.exe"
        elif system == "Darwin":  # macOS
            possible_paths = [
                "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                "/usr/local/bin/soffice",
                "/opt/homebrew/bin/soffice",
            ]
            if shutil.which("soffice"):
                return "soffice"
        else:  # Linux
            possible_paths = [
                "/usr/bin/soffice",
                "/usr/local/bin/soffice",
                "/opt/libreoffice*/program/soffice",
            ]
            if shutil.which("soffice"):
                return "soffice"
        
        # Check possible paths
        for path in possible_paths:
            if "*" in path:
                # Handle glob patterns
                import glob
                matches = glob.glob(path)
                if matches:
                    path = matches[0]
            
            if os.path.exists(path) and os.access(path, os.X_OK):
                logger.info(f"Found LibreOffice at: {path}")
                return path
        
        logger.warning("LibreOffice not found in common locations")
        return None
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file for cache key"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read file in chunks to handle large files
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _get_cache_path(self, pptx_path: str) -> Path:
        """Get cache file path for a PPTX file"""
        file_hash = self._calculate_file_hash(pptx_path)
        return self.cache_dir / f"{file_hash}.pdf"
    
    def _is_cache_valid(self, pptx_path: str, cache_path: Path) -> bool:
        """
        Check if cached PDF is still valid.
        
        Cache is valid if:
        1. Cache file exists
        2. Source file hasn't been modified since cache was created
        """
        if not cache_path.exists():
            return False
        
        try:
            pptx_mtime = os.path.getmtime(pptx_path)
            cache_mtime = os.path.getmtime(cache_path)
            
            # Cache is valid if it's newer than the source file
            return cache_mtime >= pptx_mtime
        except OSError:
            return False
    
    async def convert_pptx_to_pdf(
        self, 
        pptx_path: str, 
        output_path: Optional[str] = None,
        use_cache: bool = True
    ) -> str:
        """
        Convert PPTX file to PDF.
        
        Args:
            pptx_path: Path to PPTX file
            output_path: Optional output path. If None, uses cache directory.
            use_cache: Whether to use cached conversion if available
            
        Returns:
            Path to converted PDF file
            
        Raises:
            FileNotFoundError: If PPTX file doesn't exist
            RuntimeError: If conversion fails
        """
        if not self.libreoffice_path:
            raise RuntimeError("LibreOffice not found. Please install LibreOffice to enable PPTX preview.")
        
        pptx_path_obj = Path(pptx_path)
        if not pptx_path_obj.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")
        
        # Check cache first
        if use_cache:
            cache_path = self._get_cache_path(pptx_path)
            if self._is_cache_valid(pptx_path, cache_path):
                logger.info(f"Using cached PDF for {pptx_path_obj.name}")
                return str(cache_path)
        
        # Determine output path
        if output_path is None:
            output_path = str(self._get_cache_path(pptx_path))
        
        output_path_obj = Path(output_path)
        output_dir = output_path_obj.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Run conversion in thread pool (subprocess is blocking)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, 
            self._convert_sync, 
            pptx_path, 
            str(output_dir)
        )
        
        # LibreOffice outputs with same name but .pdf extension
        # It uses the original filename, so we need to find it
        expected_pdf = output_dir / f"{pptx_path_obj.stem}.pdf"
        
        if not expected_pdf.exists():
            raise RuntimeError(f"PDF conversion failed: output file not found at {expected_pdf}")
        
        # Move/rename to final location if needed
        if expected_pdf != output_path_obj:
            # If target exists, remove it first
            if output_path_obj.exists():
                output_path_obj.unlink()
            shutil.move(str(expected_pdf), str(output_path_obj))
        
        logger.info(f"Successfully converted {pptx_path_obj.name} to PDF: {output_path_obj}")
        return str(output_path_obj)
    
    def _convert_sync(self, pptx_path: str, output_dir: str):
        """
        Synchronous conversion using LibreOffice headless mode.
        
        Args:
            pptx_path: Path to PPTX file
            output_dir: Directory to save PDF output
        """
        try:
            # Build LibreOffice command
            cmd = [
                self.libreoffice_path,
                "--headless",
                "--convert-to", "pdf",
                "--outdir", output_dir,
                pptx_path
            ]
            
            logger.debug(f"Running LibreOffice conversion: {' '.join(cmd)}")
            
            # Run conversion with timeout
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.conversion_timeout,
                check=False
            )
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise RuntimeError(
                    f"LibreOffice conversion failed (exit code {result.returncode}): {error_msg}"
                )
            
            logger.debug(f"LibreOffice conversion completed successfully")
            
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"PPTX conversion timed out after {self.conversion_timeout} seconds. "
                "File may be too large or complex."
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"LibreOffice executable not found at: {self.libreoffice_path}"
            )
        except Exception as e:
            raise RuntimeError(f"PPTX conversion failed: {str(e)}")
    
    def get_cached_pdf(self, pptx_path: str) -> Optional[str]:
        """
        Get cached PDF if available and valid.
        
        Args:
            pptx_path: Path to PPTX file
            
        Returns:
            Path to cached PDF, or None if not available/invalid
        """
        cache_path = self._get_cache_path(pptx_path)
        if self._is_cache_valid(pptx_path, cache_path):
            return str(cache_path)
        return None
    
    def clear_cache(self, older_than_days: Optional[int] = None):
        """
        Clear cached PDF files.
        
        Args:
            older_than_days: Only clear files older than this many days. 
                           If None, clears all cache.
        """
        if not self.cache_dir.exists():
            return
        
        now = datetime.now().timestamp()
        cleared_count = 0
        
        for cache_file in self.cache_dir.glob("*.pdf"):
            try:
                if older_than_days is None:
                    cache_file.unlink()
                    cleared_count += 1
                else:
                    file_age = now - cache_file.stat().st_mtime
                    age_days = file_age / (24 * 60 * 60)
                    if age_days > older_than_days:
                        cache_file.unlink()
                        cleared_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete cache file {cache_file}: {e}")
        
        logger.info(f"Cleared {cleared_count} cached PDF files")
    
    def is_available(self) -> bool:
        """Check if LibreOffice is available for conversion"""
        return self.libreoffice_path is not None and os.path.exists(self.libreoffice_path)

