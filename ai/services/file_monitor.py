import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable, Optional
import os
from pathlib import Path
import logging
import time  # Use time.time() instead of asyncio.get_event_loop().time()

logger = logging.getLogger(__name__)

class DocumentFileHandler(FileSystemEventHandler):
    def __init__(self, event_queue: asyncio.Queue, supported_extensions: set):
        self.event_queue = event_queue
        self.supported_extensions = supported_extensions
    
    def on_modified(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            self._queue_event(event.src_path, "modified")
    
    def on_created(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            self._queue_event(event.src_path, "created")
    
    def on_deleted(self, event):
        if not event.is_directory and self._is_supported_file(event.src_path):
            self._queue_event(event.src_path, "deleted")
    
    def on_moved(self, event):
        if not event.is_directory:
            if self._is_supported_file(event.src_path):
                self._queue_event(event.src_path, "deleted")
            if self._is_supported_file(event.dest_path):
                self._queue_event(event.dest_path, "created")
    
    def _is_supported_file(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in self.supported_extensions
    
    def _queue_event(self, file_path: str, event_type: str):
        try:
            # Use time.time() instead of asyncio.get_event_loop().time()
            self.event_queue.put_nowait({
                "file_path": file_path,
                "event_type": event_type,
                "timestamp": time.time()  # Fixed: Use time.time()
            })
            logger.debug(f"Queued {event_type} event for {file_path}")
        except asyncio.QueueFull:
            logger.warning(f"Event queue full, dropping {event_type} event for {file_path}")

class FileMonitorService:
    def __init__(self, document_processor, max_queue_size: int = 100):
        self.document_processor = document_processor
        self.event_queue = asyncio.Queue(maxsize=max_queue_size)
        
        # Get supported extensions from the document processor's file validator
        supported_extensions = getattr(document_processor.file_validator, 'supported_extensions', {".pdf", ".docx", ".txt"})
        
        self.file_handler = DocumentFileHandler(self.event_queue, supported_extensions)
        self.observer: Optional[Observer] = None
        self.processor_task: Optional[asyncio.Task] = None
        self.is_running = False
        
        # Debouncing
        self.pending_events = {}  # file_path -> event_info
        self.debounce_delay = 1.0  # seconds
        
        logger.info(f"File monitor initialized with supported extensions: {supported_extensions}")
    
    async def start_monitoring(self, directory_path: str):
        """Start monitoring directory for file changes"""
        if self.is_running:
            await self.stop_monitoring()
        
        # Start file observer
        self.observer = Observer()
        self.observer.schedule(self.file_handler, directory_path, recursive=True)
        self.observer.start()
        
        # Start event processor
        self.processor_task = asyncio.create_task(self._process_events())
        self.is_running = True
        
        logger.info(f"Started monitoring directory: {directory_path}")
    
    async def stop_monitoring(self):
        """Stop file monitoring"""
        self.is_running = False
        
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        
        if self.processor_task:
            self.processor_task.cancel()
            try:
                await self.processor_task
            except asyncio.CancelledError:
                pass
            self.processor_task = None
        
        # Clear pending events
        self.pending_events.clear()
        
        # Clear event queue
        while not self.event_queue.empty():
            try:
                self.event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        logger.info("Stopped file monitoring")
    
    async def _process_events(self):
        """Process file events with debouncing"""
        while self.is_running:
            try:
                # Wait for events or timeout for debouncing check
                try:
                    event = await asyncio.wait_for(self.event_queue.get(), timeout=0.5)
                    self._update_pending_event(event)
                except asyncio.TimeoutError:
                    pass
                
                # Process debounced events
                await self._process_pending_events()
                
            except asyncio.CancelledError:
                logger.info("Event processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in event processor: {e}")
                await asyncio.sleep(1)  # Brief pause on error
    
    def _update_pending_event(self, event):
        """Update pending events with debouncing logic"""
        file_path = event["file_path"]
        event_type = event["event_type"]
        timestamp = event["timestamp"]
        
        # Update or create pending event
        if file_path in self.pending_events:
            existing = self.pending_events[file_path]
            # If it's a delete event, it takes precedence
            if event_type == "deleted":
                self.pending_events[file_path] = event
            # If existing is delete, keep it unless new event is create
            elif existing["event_type"] == "deleted" and event_type == "created":
                self.pending_events[file_path] = event
            # Otherwise, update with latest timestamp
            else:
                existing["timestamp"] = timestamp
                existing["event_type"] = event_type
        else:
            self.pending_events[file_path] = event
    
    async def _process_pending_events(self):
        """Process events that have passed debounce delay"""
        current_time = time.time()  # Fixed: Use time.time()
        ready_events = []
        
        for file_path, event in list(self.pending_events.items()):
            if current_time - event["timestamp"] >= self.debounce_delay:
                ready_events.append(event)
                del self.pending_events[file_path]
        
        # Process ready events
        for event in ready_events:
            await self._process_file_event(event)
    
    async def _process_file_event(self, event):
        """Process a single file event"""
        file_path = event["file_path"]
        event_type = event["event_type"]
        
        try:
            if event_type == "deleted":
                await self.document_processor.remove_document(file_path)
                logger.info(f"Processed deletion: {file_path}")
            else:  # created or modified
                await self.document_processor.add_document(file_path)
                logger.info(f"Processed {event_type}: {file_path}")
                
        except Exception as e:
            logger.error(f"Error processing {event_type} for {file_path}: {e}")
    
    def get_status(self) -> dict:
        """Get current monitoring status"""
        return {
            "is_running": self.is_running,
            "queue_size": self.event_queue.qsize(),
            "pending_events": len(self.pending_events),
            "supported_extensions": list(self.file_handler.supported_extensions)
        }