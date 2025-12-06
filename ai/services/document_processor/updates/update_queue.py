"""
Update Queue Manager

Manages a priority queue for document updates, prioritizing based on:
- Recency (recently queried files)
- User activity (files in active sessions)
- File size (smaller files update faster)
- Change magnitude (smaller changes process faster)
- User request (explicit "update now")
"""

import asyncio
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import IntEnum

from .update_strategy import UpdateStrategy

logger = logging.getLogger(__name__)


class UpdatePriority(IntEnum):
    """Priority levels for updates"""
    LOW = 0
    NORMAL = 500
    HIGH = 750
    URGENT = 1000  # User explicitly requested update


@dataclass
class UpdateTask:
    """
    Task for update queue (ordered by priority).
    
    Note: Uses custom __lt__ for reverse ordering (higher priority = processed first).
    """
    priority: int  # Higher = more important (0-1000)
    file_path: str
    update_type: str  # "created", "modified", "deleted"
    strategy: Optional[UpdateStrategy] = None
    change_percentage: float = 0.0
    file_size_bytes: int = 0
    enqueued_at: datetime = field(default_factory=datetime.utcnow)
    last_queried: Optional[datetime] = None
    is_in_active_session: bool = False
    user_requested: bool = False  # Explicit user request
    
    def __lt__(self, other):
        """Higher priority comes first (reverse order)"""
        if not isinstance(other, UpdateTask):
            return NotImplemented
        return self.priority > other.priority
    
    def __eq__(self, other):
        """Equality comparison"""
        if not isinstance(other, UpdateTask):
            return NotImplemented
        return self.priority == other.priority and self.file_path == other.file_path


@dataclass
class UpdateResult:
    """Result of an update operation"""
    success: bool
    file_path: str
    strategy: UpdateStrategy
    chunks_updated: int
    processing_time: float
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None


class UpdateQueue:
    """
    Priority queue for managing document updates.
    
    Features:
    - Priority-based processing (important files first)
    - Active update tracking
    - Completed update history
    - Queue status monitoring
    """
    
    def __init__(self, max_queue_size: int = 1000):
        """
        Initialize UpdateQueue
        
        Args:
            max_queue_size: Maximum number of pending updates
        """
        self.queue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self.active_updates: Dict[str, UpdateTask] = {}  # file_path -> UpdateTask
        self.completed_updates: Dict[str, UpdateResult] = {}  # file_path -> UpdateResult
        self.failed_updates: Dict[str, UpdateResult] = {}  # file_path -> UpdateResult
        self._lock = asyncio.Lock()
        
        logger.info(f"UpdateQueue initialized with max_size={max_queue_size}")
    
    async def enqueue(
        self,
        file_path: str,
        update_type: str = "modified",
        priority: Optional[int] = None,
        strategy: Optional[UpdateStrategy] = None,
        change_percentage: float = 0.0,
        file_size_bytes: int = 0,
        last_queried: Optional[datetime] = None,
        is_in_active_session: bool = False,
        user_requested: bool = False
    ) -> bool:
        """
        Add update to priority queue.
        
        Args:
            file_path: Path to file to update
            update_type: Type of update ("created", "modified", "deleted")
            priority: Explicit priority (0-1000). If None, will be calculated.
            strategy: Update strategy (optional, can be set later)
            change_percentage: Percentage of chunks that changed (0.0-1.0)
            file_size_bytes: File size in bytes
            last_queried: When file was last queried (for recency boost)
            is_in_active_session: Whether file is in active chat session
            user_requested: Whether user explicitly requested update
            
        Returns:
            True if enqueued successfully, False if queue is full
        """
        async with self._lock:
            # Check if already in queue or being processed
            if file_path in self.active_updates:
                logger.debug(f"File {file_path} already being processed, skipping duplicate")
                return False
            
            # Calculate priority if not provided
            if priority is None:
                priority = self._calculate_priority(
                    file_path=file_path,
                    last_queried=last_queried or datetime.utcnow(),
                    is_in_active_session=is_in_active_session,
                    file_size_bytes=file_size_bytes,
                    change_percentage=change_percentage,
                    user_requested=user_requested
                )
            
            # Create task
            task = UpdateTask(
                priority=priority,
                file_path=file_path,
                update_type=update_type,
                strategy=strategy,
                change_percentage=change_percentage,
                file_size_bytes=file_size_bytes,
                enqueued_at=datetime.utcnow(),
                last_queried=last_queried,
                is_in_active_session=is_in_active_session,
                user_requested=user_requested
            )
            
            try:
                self.queue.put_nowait(task)
                logger.info(f"Enqueued update for {file_path} with priority {priority}")
                return True
            except asyncio.QueueFull:
                logger.warning(f"Update queue full, cannot enqueue {file_path}")
                return False
    
    async def get_next(self, timeout: float = 1.0) -> Optional[UpdateTask]:
        """
        Get next update to process (blocking).
        
        Args:
            timeout: Maximum time to wait for a task (seconds)
            
        Returns:
            UpdateTask if available, None if timeout
        """
        try:
            task = await asyncio.wait_for(self.queue.get(), timeout=timeout)
            async with self._lock:
                self.active_updates[task.file_path] = task
            logger.debug(f"Dequeued update for {task.file_path} (priority {task.priority})")
            return task
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"Error getting next update: {e}")
            return None
    
    async def mark_completed(
        self,
        file_path: str,
        result: UpdateResult
    ):
        """
        Mark an update as completed.
        
        Args:
            file_path: Path to file that was updated
            result: UpdateResult with update details
        """
        async with self._lock:
            if file_path in self.active_updates:
                del self.active_updates[file_path]
            
            result.completed_at = datetime.utcnow()
            
            if result.success:
                self.completed_updates[file_path] = result
                # Keep only last 100 completed updates to prevent memory growth
                if len(self.completed_updates) > 100:
                    # Remove oldest
                    oldest = min(
                        self.completed_updates.items(),
                        key=lambda x: x[1].completed_at or datetime.min
                    )
                    del self.completed_updates[oldest[0]]
            else:
                self.failed_updates[file_path] = result
                # Keep only last 50 failed updates
                if len(self.failed_updates) > 50:
                    oldest = min(
                        self.failed_updates.items(),
                        key=lambda x: x[1].completed_at or datetime.min
                    )
                    del self.failed_updates[oldest[0]]
            
            logger.info(f"Marked update completed for {file_path}: success={result.success}")
    
    async def mark_failed(
        self,
        file_path: str,
        error_message: str
    ):
        """Mark an update as failed"""
        result = UpdateResult(
            success=False,
            file_path=file_path,
            strategy=UpdateStrategy.FULL_REINDEX,  # Default
            chunks_updated=0,
            processing_time=0.0,
            error_message=error_message
        )
        await self.mark_completed(file_path, result)
    
    def _calculate_priority(
        self,
        file_path: str,
        last_queried: datetime,
        is_in_active_session: bool,
        file_size_bytes: int,
        change_percentage: float,
        user_requested: bool
    ) -> int:
        """
        Calculate priority for an update task.
        
        Priority factors (0-1000):
        - User request: +1000 (urgent)
        - Active session: +200
        - Recency: 0-400 (recently queried = higher)
        - File size: 0-200 (smaller = faster = higher)
        - Change magnitude: 0-200 (smaller changes = faster = higher)
        
        Args:
            file_path: Path to file
            last_queried: When file was last queried
            is_in_active_session: Whether in active session
            file_size_bytes: File size in bytes
            change_percentage: Percentage of chunks changed
            user_requested: Whether user explicitly requested
            
        Returns:
            Priority score (0-1000, higher = more important)
        """
        priority = 0
        
        # User request gets top priority
        if user_requested:
            return UpdatePriority.URGENT
        
        # Active session boost (200 points)
        if is_in_active_session:
            priority += 200
        
        # Recency boost (0-400 points)
        # More recent = higher priority
        now = datetime.utcnow()
        hours_since_query = (now - last_queried).total_seconds() / 3600
        
        # Decay: 400 points for < 1 hour, 0 points for > 40 hours
        recency_score = max(0, 400 - (hours_since_query * 10))
        priority += int(recency_score)
        
        # Size bonus (0-200 points)
        # Smaller files = faster updates = higher priority
        file_size_mb = file_size_bytes / (1024 * 1024)
        size_score = max(0, 200 - (file_size_mb * 2))  # 0 MB = 200, 100 MB = 0
        priority += int(size_score)
        
        # Change magnitude bonus (0-200 points)
        # Smaller changes = faster updates = higher priority
        change_score = (1.0 - change_percentage) * 200
        priority += int(change_score)
        
        # Clamp to valid range
        return max(0, min(UpdatePriority.URGENT, int(priority)))
    
    def get_status(self) -> Dict:
        """
        Get current queue status.
        
        Returns:
            Dictionary with queue statistics
        """
        return {
            "pending": self.queue.qsize(),
            "processing": len(self.active_updates),
            "completed": len(self.completed_updates),
            "failed": len(self.failed_updates),
            "active_files": list(self.active_updates.keys()),
            "queue_size": self.queue.qsize()
        }
    
    def get_pending_tasks(self, limit: int = 10) -> List[Dict]:
        """
        Get list of pending tasks (for monitoring/debugging).
        Note: This is a snapshot, actual queue order may differ.
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            List of task dictionaries
        """
        # Note: asyncio.PriorityQueue doesn't support iteration
        # This is a limitation - we can't peek at the queue
        # For now, return active updates
        tasks = []
        for file_path, task in list(self.active_updates.items())[:limit]:
            tasks.append({
                "file_path": task.file_path,
                "priority": task.priority,
                "update_type": task.update_type,
                "enqueued_at": task.enqueued_at.isoformat(),
                "strategy": task.strategy.value if task.strategy else None
            })
        return tasks
    
    async def clear(self):
        """Clear all pending updates (use with caution)"""
        async with self._lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self.active_updates.clear()
            logger.warning("Update queue cleared")

