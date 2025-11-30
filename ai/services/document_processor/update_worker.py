"""
Update Worker

Background worker that processes update tasks from the UpdateQueue.
Coordinates ChunkDiffer, UpdateStrategySelector, and UpdateExecutor.
"""

import asyncio
import logging
from typing import Optional, List
from datetime import datetime

from .update_queue import UpdateQueue, UpdateTask, UpdateResult
from .update_executor import UpdateExecutor
from .chunk_differ import ChunkDiffer
from .update_strategy import UpdateStrategySelector
from .models import DocumentChunk

logger = logging.getLogger(__name__)


class UpdateWorker:
    """
    Background worker that processes update tasks from the queue.
    
    Flow:
    1. Get task from queue
    2. Get old chunks (if exists)
    3. Get new chunks
    4. Run ChunkDiffer to analyze changes
    5. Select update strategy
    6. Execute update with UpdateExecutor
    7. Mark task as completed
    """
    
    def __init__(
        self,
        update_queue: UpdateQueue,
        update_executor: UpdateExecutor,
        chunk_differ: ChunkDiffer,
        strategy_selector: UpdateStrategySelector,
        chunker,  # DocumentChunker
        text_extractor  # TextExtractor
    ):
        """
        Initialize UpdateWorker
        
        Args:
            update_queue: Update queue to process tasks from
            update_executor: Executor to run updates
            chunk_differ: Chunk differ to analyze changes
            strategy_selector: Strategy selector to choose update approach
            chunker: Document chunker to create chunks
            text_extractor: Text extractor to get document text
        """
        self.update_queue = update_queue
        self.update_executor = update_executor
        self.chunk_differ = chunk_differ
        self.strategy_selector = strategy_selector
        self.chunker = chunker
        self.text_extractor = text_extractor
        
        self.is_running = False
        self.worker_task: Optional[asyncio.Task] = None
        
        logger.info("UpdateWorker initialized")
    
    async def start(self):
        """Start the update worker"""
        if self.is_running:
            logger.warning("Update worker is already running")
            return
        
        self.is_running = True
        self.worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Update worker started")
    
    async def stop(self):
        """Stop the update worker"""
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
        """Main worker loop that processes tasks from queue"""
        logger.info("Update worker loop started")
        
        while self.is_running:
            try:
                # Get next task from queue (with timeout)
                task = await self.update_queue.get_next(timeout=1.0)
                
                if task is None:
                    # No tasks available, continue waiting
                    continue
                
                # Process the task
                await self._process_task(task)
                
            except asyncio.CancelledError:
                logger.info("Update worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in update worker loop: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause before retrying
    
    async def _process_task(self, task: UpdateTask):
        """
        Process a single update task.
        
        Args:
            task: Update task to process
        """
        logger.info(f"Processing update task for {task.file_path}")
        
        try:
            # Get old chunks if document exists
            old_chunks = await self._get_old_chunks(task.file_path)
            
            # Get new chunks
            new_chunks = await self._get_new_chunks(task.file_path)
            
            # Analyze changes with ChunkDiffer
            diff_result = None
            if old_chunks and new_chunks:
                diff_result = self.chunk_differ.diff_chunks(old_chunks, new_chunks)
                
                # Select update strategy if not already set
                if task.strategy is None:
                    strategy_result = self.strategy_selector.select_strategy(
                        diff_result=diff_result,
                        total_chunks=len(new_chunks),
                        file_size_bytes=task.file_size_bytes
                    )
                    task.strategy = strategy_result.strategy
                    logger.info(f"Selected strategy: {task.strategy.value} ({strategy_result.reason})")
            
            # Execute update
            result = await self.update_executor.execute_update(task, diff_result)
            
            # Mark task as completed
            await self.update_queue.mark_completed(task.file_path, result)
            
            if result.success:
                logger.info(f"Update completed for {task.file_path}: {result.chunks_updated} chunks, {result.processing_time:.2f}s")
            else:
                logger.error(f"Update failed for {task.file_path}: {result.error_message}")
                
        except Exception as e:
            logger.error(f"Error processing task for {task.file_path}: {e}", exc_info=True)
            await self.update_queue.mark_failed(task.file_path, str(e))
    
    async def _get_old_chunks(self, file_path: str) -> Optional[List[DocumentChunk]]:
        """
        Get old chunks for a file (if it exists).
        
        Args:
            file_path: Path to file
            
        Returns:
            List of old chunks or None if file doesn't exist
        """
        try:
            # Get chunks from vector store
            chunks_data = self.update_executor.vector_store.get_document_chunks(file_path)
            
            if not chunks_data or not chunks_data.get('ids'):
                return None
            
            # Reconstruct DocumentChunk objects
            old_chunks = []
            documents = chunks_data.get('documents', [])
            metadatas = chunks_data.get('metadatas', [])
            
            for i, doc_text in enumerate(documents):
                metadata = metadatas[i] if i < len(metadatas) else {}
                chunk = DocumentChunk(
                    text=doc_text,
                    chunk_id=metadata.get('chunk_id', i),
                    total_chunks=len(documents),
                    file_path=file_path,
                    start_pos=metadata.get('start_pos', 0),
                    end_pos=metadata.get('end_pos', len(doc_text))
                )
                old_chunks.append(chunk)
            
            return old_chunks
            
        except Exception as e:
            logger.warning(f"Could not get old chunks for {file_path}: {e}")
            return None
    
    async def _get_new_chunks(self, file_path: str) -> List[DocumentChunk]:
        """
        Get new chunks for a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            List of new chunks
        """
        # Extract text
        text = await self.text_extractor.extract_text_async(file_path)
        
        if not text or not text.strip():
            raise ValueError(f"No text extracted from {file_path}")
        
        # Create chunks
        chunks = self.chunker.create_chunks(text, file_path)
        
        return chunks

