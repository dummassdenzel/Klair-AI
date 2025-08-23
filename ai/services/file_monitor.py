from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable
import os
import asyncio
import time
from collections import defaultdict

class DocumentFileHandler(FileSystemEventHandler):
    def __init__(self, on_file_change: Callable[[str, bool], None]):
        self.on_file_change = on_file_change
        self._loop = None
        self._last_processed = defaultdict(float)
        self._debounce_delay = 2.0  # 2 seconds
    
    def set_event_loop(self, loop):
        """Set the event loop for async operations"""
        self._loop = loop
    
    def on_modified(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            print(f"📝 File modified detected: {event.src_path}")
            self._debounce_file_change(event.src_path, False)
    
    def on_created(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            print(f"📄 File created detected: {event.src_path}")
            self._debounce_file_change(event.src_path, False)
    
    def on_deleted(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            print(f"🗑️ File deleted detected: {event.src_path}")
            self._debounce_file_change(event.src_path, True)
    
    def _is_supported_file(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in {".pdf", ".docx", ".txt"}
    
    def _debounce_file_change(self, file_path: str, is_deletion: bool):
        """Debounce file changes to prevent rapid processing"""
        current_time = time.time()
        last_processed = self._last_processed[file_path]
        
        # Check if enough time has passed since last processing
        if current_time - last_processed < self._debounce_delay:
            print(f"⏭️ Skipping {file_path} - too soon since last processing")
            return
        
        if self._loop and self._loop.is_running():
            # Update last processed time
            self._last_processed[file_path] = current_time
            
            # Schedule processing in the main event loop
            asyncio.run_coroutine_threadsafe(
                self._delayed_process(file_path, is_deletion), 
                self._loop
            )
            print(f"📅 Scheduled processing for {file_path} (deletion: {is_deletion})")
        else:
            print(f"⚠️ Warning: No event loop available for file change")
    
    async def _delayed_process(self, file_path: str, is_deletion: bool):
        """Process file change after debounce delay"""
        try:
            # Wait for debounce period
            await asyncio.sleep(self._debounce_delay)
            
            # Process the file change
            await self.on_file_change(file_path, is_deletion)
            print(f"✅ Processed file change: {file_path} (deletion: {is_deletion})")
                
        except asyncio.CancelledError:
            print(f"❌ Task cancelled for {file_path}")
        except Exception as e:
            print(f"❌ Error in delayed processing for {file_path}: {e}")
    
    def cleanup(self):
        """Clean up"""
        self._last_processed.clear()