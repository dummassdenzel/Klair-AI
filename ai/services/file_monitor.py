# app/services/file_monitor.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable

class DocumentFileHandler(FileSystemEventHandler):
    SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.txt'}
    
    def __init__(self, on_file_change: Callable[[str], None]):
        self.on_file_change = on_file_change
        self.debounce_delay = 1.0  # seconds
        self._pending_files = {}
    
    def on_modified(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            self._debounce_file_change(event.src_path)
    
    def _is_supported_file(self, file_path: str) -> bool:
        return any(file_path.lower().endswith(ext) for ext in self.SUPPORTED_EXTENSIONS)