from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable
import os
import asyncio

class DocumentFileHandler(FileSystemEventHandler):
    def __init__(self, on_file_change: Callable[[str, bool], None]):
        self.on_file_change = on_file_change
        self._loop = None
    
    def set_event_loop(self, loop):
        """Set the event loop for async operations"""
        self._loop = loop
    
    def on_modified(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            print(f"📝 File modified detected: {event.src_path}")
            self._schedule_async_task(self.on_file_change(event.src_path, False))
    
    def on_created(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            print(f"📄 File created detected: {event.src_path}")
            self._schedule_async_task(self.on_file_change(event.src_path, False))
    
    def on_deleted(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            print(f"🗑️ File deleted detected: {event.src_path}")
            self._schedule_async_task(self.on_file_change(event.src_path, True))
    
    def _is_supported_file(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in {".pdf", ".docx", ".txt"}
    
    def _schedule_async_task(self, coro):
        """Schedule async task in the main event loop"""
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(coro, self._loop)
                print(f"🔄 Scheduled file change task")
            except Exception as e:
                print(f"❌ Error scheduling file change: {e}")
        else:
            print(f"⚠️ Warning: No event loop available for file change")