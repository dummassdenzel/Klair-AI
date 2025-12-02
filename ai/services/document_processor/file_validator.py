import hashlib
import logging
import os
from typing import Tuple, Dict, Optional
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)


class FileValidator:
    """Service for validating files and managing file metadata"""
    
    def __init__(self, max_file_size_mb: int = 50):
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.supported_extensions = {".pdf", ".docx", ".txt", ".xlsx", ".xls"}
    
    def validate_file(self, file_path: str) -> Tuple[bool, str]:
        """Validate file and return (is_valid, error_message)"""
        try:
            path_obj = Path(file_path)
            
            if not path_obj.exists():
                return False, "File does not exist"
            
            if not path_obj.is_file():
                return False, "Path is not a file"
            
            if path_obj.suffix.lower() not in self.supported_extensions:
                return False, f"Unsupported file type: {path_obj.suffix}"
            
            file_size = path_obj.stat().st_size
            if file_size > self.max_file_size_bytes:
                return False, f"File too large ({file_size / 1024 / 1024:.1f}MB)"
            
            if file_size == 0:
                return False, "File is empty"
            
            if not os.access(file_path, os.R_OK):
                return False, "File not readable"
            
            return True, ""
            
        except Exception as e:
            return False, f"Validation error: {e}"
    
    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file content efficiently"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                # Read in larger chunks for better performance
                for chunk in iter(lambda: f.read(65536), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating hash for {file_path}: {e}")
            return ""
    
    def extract_file_metadata(self, file_path: str) -> Dict:
        """Extract comprehensive file metadata"""
        try:
            path_obj = Path(file_path)
            stat_info = path_obj.stat()
            
            return {
                "file_path": str(file_path),
                "file_name": path_obj.name,
                "file_type": path_obj.suffix.lower(),
                "size_bytes": stat_info.st_size,
                "size_mb": round(stat_info.st_size / 1024 / 1024, 2),
                "created_at": datetime.fromtimestamp(stat_info.st_ctime),
                "modified_at": datetime.fromtimestamp(stat_info.st_mtime),
                "accessed_at": datetime.fromtimestamp(stat_info.st_atime),
                "is_readable": os.access(file_path, os.R_OK),
                "is_writable": os.access(file_path, os.W_OK),
                "hash": self.calculate_file_hash(file_path)
            }
        except Exception as e:
            logger.error(f"Error extracting metadata for {file_path}: {e}")
            return {}
    
    def is_supported_file(self, file_path: str) -> bool:
        """Check if file type is supported"""
        return Path(file_path).suffix.lower() in self.supported_extensions
    
    def get_file_size_mb(self, file_path: str) -> float:
        """Get file size in MB"""
        try:
            return Path(file_path).stat().st_size / 1024 / 1024
        except Exception:
            return 0.0
    
    def has_file_changed(self, file_path: str, previous_hash: str) -> bool:
        """Check if file has changed by comparing hashes"""
        current_hash = self.calculate_file_hash(file_path)
        return current_hash != previous_hash if current_hash else True
