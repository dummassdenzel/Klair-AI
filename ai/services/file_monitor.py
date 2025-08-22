# app/services/file_monitor.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable
import time
import os
import threading

class DocumentFileHandler(FileSystemEventHandler):
    def __init__(self, on_file_change: Callable[[str], None]):
        self.on_file_change = on_file_change
        self.debounce_delay = 1.0  # seconds
        self._pending_files = {}
        self._lock = threading.Lock()
    
    def on_modified(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            self._debounce_file_change(event.src_path)
    
    def on_created(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            self._debounce_file_change(event.src_path)
    
    def on_deleted(self, event):
        # Handle file deletion if needed
        # This would require additional logic in DocumentManager
        pass
    
    def _is_supported_file(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in {".pdf", ".docx", ".txt"}
    
    def _debounce_file_change(self, file_path: str):
        """Debounce file changes to prevent multiple rapid updates"""
        with self._lock:
            current_time = time.time()
            self._pending_files[file_path] = current_time
            
            # Start a timer to process this file after the debounce period
            threading.Timer(
                self.debounce_delay,
                self._process_file_if_ready,
                args=[file_path, current_time]
            ).start()
    
    def _process_file_if_ready(self, file_path: str, timestamp: float):
        """Process the file if it hasn't been updated since the timestamp"""
        with self._lock:
            if file_path in self._pending_files and self._pending_files[file_path] == timestamp:
                # Remove from pending
                del self._pending_files[file_path]
                # Notify callback
                self.on_file_change(file_path)