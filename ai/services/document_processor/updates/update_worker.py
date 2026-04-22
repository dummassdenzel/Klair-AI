"""
UpdateWorker — background worker that drains the UpdateQueue.

Each task delegates directly to IndexingService.add_document() (for
created/modified events) or IndexingService.remove_document() (for deleted).
The old ChunkDiffer / UpdateStrategySelector / UpdateExecutor pipeline is gone —
add_document() already does hash comparison + delete-old + reinsert-new,
which is exactly what all three strategies boiled down to.
"""

import asyncio
import logging
from typing import Optional

from .update_queue import UpdateQueue, UpdateTask, UpdateResult

logger = logging.getLogger(__name__)


class UpdateWorker:
    """Background worker that processes update tasks from the queue."""

    def __init__(self, update_queue: UpdateQueue, indexing_service) -> None:
        self.update_queue = update_queue
        self.indexing_service = indexing_service
        self.is_running = False
        self.worker_task: Optional[asyncio.Task] = None
        logger.info("UpdateWorker initialized")

    async def start(self):
        if self.is_running:
            logger.warning("Update worker is already running")
            return
        self.is_running = True
        self.worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Update worker started")

    async def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Update worker stopped")

    async def _worker_loop(self):
        logger.info("Update worker loop started")
        while self.is_running:
            try:
                task = await self.update_queue.get_next(timeout=1.0)
                if task is None:
                    continue
                await self._process_task(task)
            except asyncio.CancelledError:
                logger.info("Update worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in update worker loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _process_task(self, task: UpdateTask):
        logger.info(f"Processing update task for {task.file_path} (type: {task.update_type})")
        start_time = asyncio.get_running_loop().time()
        try:
            if task.update_type == "deleted":
                await self.indexing_service.remove_document(task.file_path)
            else:
                await self.indexing_service.add_document(task.file_path, use_queue=False)
            elapsed = asyncio.get_running_loop().time() - start_time
            result = UpdateResult(
                success=True,
                file_path=task.file_path,
                chunks_updated=0,
                processing_time=elapsed,
            )
            await self.update_queue.mark_completed(task.file_path, result)
            logger.info(f"Update completed for {task.file_path} in {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"Error processing task for {task.file_path}: {e}", exc_info=True)
            await self.update_queue.mark_failed(task.file_path, str(e))
