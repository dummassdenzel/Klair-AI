# app/services/file_monitor.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable
import time
import os
import threading
import asyncio
from collections import defaultdict

class DocumentFileHandler(FileSystemEventHandler):
    def __init__(self, on_file_change: Callable[[str], None]):
        self.on_file_change = on_file_change
        self.debounce_delay = 2.0
        self._pending_tasks = defaultdict(lambda: None)
        self._lock = threading.Lock()  # Use threading.Lock instead of asyncio.Lock
        self._loop = None  # Will store the event loop
    
    def set_event_loop(self, loop):
        """Set the event loop for async operations"""
        self._loop = loop
    
    def on_modified(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            self._debounce_file_change(event.src_path)
    
    def on_created(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            self._debounce_file_change(event.src_path)
    
    def on_deleted(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            # Handle file deletion
            self._handle_file_deletion(event.src_path)
    
    def _is_supported_file(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in {".pdf", ".docx", ".txt"}
    
    def _debounce_file_change(self, file_path: str):
        """Debounce file changes using threading (not async)"""
        with self._lock:
            # Cancel existing timer for this file
            if self._pending_tasks[file_path]:
                self._pending_tasks[file_path].cancel()
            
            # Create new timer
            timer = threading.Timer(
                self.debounce_delay,
                self._process_file_change,
                args=[file_path]
            )
            self._pending_tasks[file_path] = timer
            timer.start()
    
    def _process_file_change(self, file_path: str):
        """Process the file change in the main event loop"""
        if self._loop and self._loop.is_running():
            # Schedule the async callback in the main event loop
            asyncio.run_coroutine_threadsafe(
                self.on_file_change(file_path),
                self._loop
            )
        else:
            # Fallback: run synchronously if no event loop
            print(f"Warning: No event loop available for file change: {file_path}")
    
    def _handle_file_deletion(self, file_path: str):
        """Handle file deletion"""
        if self._loop and self._loop.is_running():
            # You'll need to implement file deletion logic in your DocumentProcessor
            asyncio.run_coroutine_threadsafe(
                self.on_file_change(file_path, is_deletion=True),
                self._loop
            )
        else:
            print(f"Warning: No event loop available for file deletion: {file_path}")
    
    def cleanup(self):
        """Clean up pending timers"""
        with self._lock:
            for timer in self._pending_tasks.values():
                if timer:
                    timer.cancel()
            self._pending_tasks.clear()