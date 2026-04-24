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
import signal
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
    
    async def convert_to_pdf(
        self,
        file_path: str,
        output_path: Optional[str] = None,
        use_cache: bool = True,
    ) -> str:
        """
        Convert any LibreOffice-supported file (PPTX, DOCX, etc.) to PDF.

        Args:
            file_path: Path to the source file
            output_path: Optional explicit output path. If None, uses cache directory.
            use_cache: Whether to return a cached conversion if still valid

        Returns:
            Path to the converted PDF file

        Raises:
            FileNotFoundError: If the source file does not exist
            RuntimeError: If LibreOffice is unavailable or conversion fails
        """
        if not self.libreoffice_path:
            raise RuntimeError(
                "LibreOffice not found. Please install LibreOffice to enable document preview."
            )

        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if use_cache:
            cache_path = self._get_cache_path(file_path)
            if self._is_cache_valid(file_path, cache_path):
                logger.info("Using cached PDF for %s", src.name)
                return str(cache_path)

        if output_path is None:
            output_path = str(self._get_cache_path(file_path))

        output_path_obj = Path(output_path)
        output_dir = output_path_obj.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(self._convert_sync, file_path, str(output_dir))

        expected_pdf = output_dir / f"{src.stem}.pdf"
        if not expected_pdf.exists():
            raise RuntimeError(
                f"PDF conversion failed: output file not found at {expected_pdf}"
            )

        if expected_pdf != output_path_obj:
            if output_path_obj.exists():
                output_path_obj.unlink()
            shutil.move(str(expected_pdf), str(output_path_obj))

        logger.info("Converted %s → %s", src.name, output_path_obj)
        return str(output_path_obj)

    async def convert_pptx_to_pdf(
        self,
        pptx_path: str,
        output_path: Optional[str] = None,
        use_cache: bool = True,
    ) -> str:
        """Backward-compatible alias for convert_to_pdf."""
        return await self.convert_to_pdf(pptx_path, output_path, use_cache)
    
    def _convert_sync(self, pptx_path: str, output_dir: str):
        """
        Synchronous conversion using LibreOffice headless mode.
        
        Args:
            pptx_path: Path to PPTX file
            output_dir: Directory to save PDF output
        """
        process = None
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
            
            # Create process with proper cleanup handling
            # Use Popen for better control over process lifecycle
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # Create new process group on Windows to allow proper termination
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0
            )
            
            # Wait with timeout
            try:
                stdout, stderr = process.communicate(timeout=self.conversion_timeout)
            except subprocess.TimeoutExpired:
                # Kill the process and its children
                try:
                    if platform.system() == "Windows":
                        # On Windows, use taskkill to kill process tree
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                            capture_output=True,
                            timeout=5
                        )
                    else:
                        # On Unix, kill process group
                        try:
                            pgid = os.getpgid(process.pid)
                            os.killpg(pgid, signal.SIGTERM)
                        except ProcessLookupError:
                            # Process already dead
                            pass
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            try:
                                pgid = os.getpgid(process.pid)
                                os.killpg(pgid, signal.SIGKILL)
                            except ProcessLookupError:
                                # Process already dead
                                pass
                except Exception as kill_error:
                    logger.warning(f"Error killing LibreOffice process: {kill_error}")
                finally:
                    process.wait()  # Ensure process is cleaned up
                
                raise RuntimeError(
                    f"PPTX conversion timed out after {self.conversion_timeout} seconds. "
                    "File may be too large or complex."
                )
            
            if process.returncode != 0:
                error_msg = stderr or stdout or "Unknown error"
                raise RuntimeError(
                    f"LibreOffice conversion failed (exit code {process.returncode}): {error_msg}"
                )
            
            logger.debug(f"LibreOffice conversion completed successfully")
            
        except subprocess.TimeoutExpired:
            # This should not happen as we handle it above, but keep for safety
            raise RuntimeError(
                f"PPTX conversion timed out after {self.conversion_timeout} seconds. "
                "File may be too large or complex."
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"LibreOffice executable not found at: {self.libreoffice_path}"
            )
        except Exception as e:
            # Ensure process is cleaned up even on unexpected errors
            if process and process.poll() is None:
                try:
                    if platform.system() == "Windows":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                            capture_output=True,
                            timeout=5
                        )
                    else:
                        try:
                            pgid = os.getpgid(process.pid)
                            os.killpg(pgid, signal.SIGTERM)
                        except ProcessLookupError:
                            # Process already dead
                            pass
                except Exception:
                    pass
            raise RuntimeError(f"PPTX conversion failed: {str(e)}")
        finally:
            # Ensure process is terminated
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
    
    def get_cached_pdf(self, file_path: str) -> Optional[str]:
        """Return path to cached PDF if still valid, else None."""
        cache_path = self._get_cache_path(file_path)
        if self._is_cache_valid(file_path, cache_path):
            return str(cache_path)
        return None
    
    def clear_cache(self, older_than_days: Optional[int] = None):
        """
        Clear cached PDF files.
        
        Args:
            older_than_days: Only clear files older than this many days. 
                           If None, clears all cache.
                           
        Returns:
            dict with statistics about cleared cache
        """
        if not self.cache_dir.exists():
            return {
                "cleared_count": 0,
                "total_size_bytes": 0,
                "cache_dir": str(self.cache_dir)
            }
        
        now = datetime.now().timestamp()
        cleared_count = 0
        total_size_bytes = 0
        
        for cache_file in self.cache_dir.glob("*.pdf"):
            try:
                file_size = cache_file.stat().st_size
                should_delete = False
                
                if older_than_days is None:
                    should_delete = True
                else:
                    file_age = now - cache_file.stat().st_mtime
                    age_days = file_age / (24 * 60 * 60)
                    if age_days > older_than_days:
                        should_delete = True
                
                if should_delete:
                    cache_file.unlink()
                    cleared_count += 1
                    total_size_bytes += file_size
            except Exception as e:
                logger.warning(f"Failed to delete cache file {cache_file}: {e}")
        
        logger.info(f"Cleared {cleared_count} cached PDF files ({total_size_bytes / (1024*1024):.2f} MB)")
        
        return {
            "cleared_count": cleared_count,
            "total_size_bytes": total_size_bytes,
            "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir)
        }
    
    def get_cache_stats(self) -> dict:
        """
        Get statistics about the cache directory.
        
        Returns:
            dict with cache statistics
        """
        if not self.cache_dir.exists():
            return {
                "file_count": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0,
                "cache_dir": str(self.cache_dir),
                "oldest_file_age_days": 0,
                "newest_file_age_days": 0
            }
        
        cache_files = list(self.cache_dir.glob("*.pdf"))
        file_count = len(cache_files)
        total_size_bytes = sum(f.stat().st_size for f in cache_files if f.exists())
        
        if cache_files:
            now = datetime.now().timestamp()
            file_ages = [
                (now - f.stat().st_mtime) / (24 * 60 * 60)
                for f in cache_files
                if f.exists()
            ]
            oldest_age = max(file_ages) if file_ages else 0
            newest_age = min(file_ages) if file_ages else 0
        else:
            oldest_age = 0
            newest_age = 0
        
        return {
            "file_count": file_count,
            "total_size_bytes": total_size_bytes,
            "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir),
            "oldest_file_age_days": round(oldest_age, 2),
            "newest_file_age_days": round(newest_age, 2)
        }
    
    def is_available(self) -> bool:
        """Check if LibreOffice is available for conversion"""
        return self.libreoffice_path is not None and os.path.exists(self.libreoffice_path)

