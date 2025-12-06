"""
Update Executor with Rollback Support

Executes document updates with:
- Checkpoint creation before updates
- Strategy-based execution (FULL_REINDEX, CHUNK_UPDATE, SMART_HYBRID)
- Update verification
- Automatic rollback on failure
- Progress tracking
"""

import logging
import asyncio
from typing import Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass

from .update_queue import UpdateTask, UpdateResult
from .update_strategy import UpdateStrategy
from ..models import DocumentChunk, ChunkDiffResult
from .chunk_differ import ChunkDiffer
from ..storage.vector_store import VectorStoreService
from ..storage.bm25_service import BM25Service
from ..extraction.text_extractor import TextExtractor
from ..extraction.chunker import DocumentChunker
from ..extraction.embedding_service import EmbeddingService
from database import DatabaseService

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """Checkpoint data for rollback"""
    file_path: str
    timestamp: datetime
    old_chunks_data: List[Dict]  # Serialized chunk data
    old_metadata: Optional[Dict] = None
    old_bm25_ids: List[str] = None  # BM25 document IDs


class UpdateExecutor:
    """
    Executes document updates with rollback support.
    
    Features:
    - Creates checkpoints before updates
    - Executes updates based on strategy
    - Verifies update success
    - Rolls back on failure
    - Tracks progress
    """
    
    def __init__(
        self,
        vector_store: VectorStoreService,
        bm25_service: BM25Service,
        text_extractor: TextExtractor,
        chunker: DocumentChunker,
        embedding_service: EmbeddingService,
        database_service: DatabaseService,
        chunk_differ: ChunkDiffer
    ):
        """
        Initialize UpdateExecutor
        
        Args:
            vector_store: Vector store service
            bm25_service: BM25 keyword search service
            text_extractor: Text extraction service
            chunker: Document chunking service
            embedding_service: Embedding generation service
            database_service: Database service
            chunk_differ: Chunk differ for incremental updates
        """
        self.vector_store = vector_store
        self.bm25_service = bm25_service
        self.text_extractor = text_extractor
        self.chunker = chunker
        self.embedding_service = embedding_service
        self.database_service = database_service
        self.chunk_differ = chunk_differ
        
        logger.info("UpdateExecutor initialized")
    
    async def execute_update(
        self,
        task: UpdateTask,
        diff_result: Optional[ChunkDiffResult] = None
    ) -> UpdateResult:
        """
        Execute update with rollback support.
        
        Args:
            task: Update task to execute
            diff_result: Optional chunk diff result (for incremental updates)
            
        Returns:
            UpdateResult with update details
        """
        start_time = asyncio.get_event_loop().time()
        
        logger.info(f"Executing update for {task.file_path} with strategy {task.strategy}")
        
        # 1. Create checkpoint
        checkpoint = await self._create_checkpoint(task.file_path)
        
        try:
            # 2. Execute update based on strategy
            if task.strategy == UpdateStrategy.CHUNK_UPDATE:
                chunks_updated = await self._execute_chunk_update(task, diff_result)
            elif task.strategy == UpdateStrategy.SMART_HYBRID:
                chunks_updated = await self._execute_smart_hybrid(task, diff_result)
            else:  # FULL_REINDEX
                chunks_updated = await self._execute_full_reindex(task)
            
            # 3. Verify update success
            await self._verify_update(task.file_path)
            
            processing_time = asyncio.get_event_loop().time() - start_time
            
            result = UpdateResult(
                success=True,
                file_path=task.file_path,
                strategy=task.strategy or UpdateStrategy.FULL_REINDEX,
                chunks_updated=chunks_updated,
                processing_time=processing_time
            )
            
            logger.info(f"Update completed successfully for {task.file_path} ({chunks_updated} chunks, {processing_time:.2f}s)")
            return result
            
        except Exception as e:
            # 4. Rollback on failure
            logger.error(f"Update failed for {task.file_path}: {e}, rolling back...")
            await self._rollback(checkpoint)
            
            processing_time = asyncio.get_event_loop().time() - start_time
            
            result = UpdateResult(
                success=False,
                file_path=task.file_path,
                strategy=task.strategy or UpdateStrategy.FULL_REINDEX,
                chunks_updated=0,
                processing_time=processing_time,
                error_message=str(e)
            )
            
            logger.error(f"Rollback completed for {task.file_path}")
            return result
    
    async def _create_checkpoint(self, file_path: str) -> Checkpoint:
        """
        Create checkpoint of current state for rollback.
        
        Args:
            file_path: Path to file
            
        Returns:
            Checkpoint with current state
        """
        logger.debug(f"Creating checkpoint for {file_path}")
        
        # Get old chunks from vector store
        old_chunks_data = self.vector_store.get_document_chunks(file_path)
        old_chunks_list = []
        
        if old_chunks_data and old_chunks_data.get('ids'):
            # Convert ChromaDB format to serializable format
            for i, chunk_id in enumerate(old_chunks_data.get('ids', [])):
                old_chunks_list.append({
                    'id': chunk_id,
                    'text': old_chunks_data.get('documents', [])[i] if old_chunks_data.get('documents') else '',
                    'metadata': old_chunks_data.get('metadatas', [])[i] if old_chunks_data.get('metadatas') else {},
                    'embedding': old_chunks_data.get('embeddings', [])[i] if old_chunks_data.get('embeddings') else None
                })
        
        # Get old metadata from database
        old_metadata = None
        try:
            from database.database import get_db
            from database.models import IndexedDocument
            from sqlalchemy import select
            
            async for db_session in get_db():
                stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
                result = await db_session.execute(stmt)
                doc = result.scalar_one_or_none()
                if doc:
                    old_metadata = {
                        'file_hash': doc.file_hash,
                        'file_size': doc.file_size,
                        'chunks_count': doc.chunks_count,
                        'content_preview': doc.content_preview,
                        'processing_status': doc.processing_status
                    }
                break
        except Exception as e:
            logger.warning(f"Could not get old metadata for checkpoint: {e}")
        
        # Get BM25 IDs (if BM25 service supports it)
        old_bm25_ids = []  # BM25 doesn't have a direct way to get IDs, so we'll track what we add
        
        checkpoint = Checkpoint(
            file_path=file_path,
            timestamp=datetime.utcnow(),
            old_chunks_data=old_chunks_list,
            old_metadata=old_metadata,
            old_bm25_ids=old_bm25_ids
        )
        
        logger.debug(f"Checkpoint created for {file_path} ({len(old_chunks_list)} chunks)")
        return checkpoint
    
    async def _rollback(self, checkpoint: Checkpoint):
        """
        Restore previous state from checkpoint.
        
        Args:
            checkpoint: Checkpoint to restore from
        """
        logger.warning(f"Rolling back {checkpoint.file_path} to state at {checkpoint.timestamp}")
        
        try:
            # Remove current chunks
            await self.vector_store.remove_document_chunks(checkpoint.file_path)
            
            # Restore old chunks if they existed
            if checkpoint.old_chunks_data:
                # Reconstruct chunks and embeddings
                chunks = []
                embeddings = []
                
                for chunk_data in checkpoint.old_chunks_data:
                    # Recreate DocumentChunk from data
                    chunk = DocumentChunk(
                        text=chunk_data['text'],
                        chunk_id=chunk_data['metadata'].get('chunk_id', 0),
                        total_chunks=len(checkpoint.old_chunks_data),
                        file_path=checkpoint.file_path,
                        start_pos=chunk_data['metadata'].get('start_pos', 0),
                        end_pos=chunk_data['metadata'].get('end_pos', len(chunk_data['text']))
                    )
                    chunks.append(chunk)
                    
                    # Use stored embedding if available, otherwise regenerate
                    if chunk_data.get('embedding'):
                        embeddings.append(chunk_data['embedding'])
                    else:
                        # Regenerate embedding (fallback)
                        embedding = self.embedding_service.encode_single_text(chunk.text)
                        embeddings.append(embedding)
                
                # Re-insert old chunks
                if chunks:
                    await self.vector_store.batch_insert_chunks(chunks, embeddings)
                    logger.debug(f"Restored {len(chunks)} chunks for {checkpoint.file_path}")
            
            # Restore old metadata if available
            if checkpoint.old_metadata:
                await self.database_service.store_document_metadata(
                    file_path=checkpoint.file_path,
                    file_hash=checkpoint.old_metadata['file_hash'],
                    file_type="",  # Not stored in checkpoint, will be updated on next successful update
                    file_size=checkpoint.old_metadata['file_size'],
                    last_modified=datetime.utcnow(),  # Approximate
                    content_preview=checkpoint.old_metadata.get('content_preview', ''),
                    chunks_count=checkpoint.old_metadata.get('chunks_count', 0),
                    processing_status=checkpoint.old_metadata.get('processing_status', 'indexed')
                )
            
            logger.info(f"Rollback completed for {checkpoint.file_path}")
            
        except Exception as e:
            logger.error(f"Error during rollback for {checkpoint.file_path}: {e}")
            raise
    
    async def _execute_full_reindex(self, task: UpdateTask) -> int:
        """
        Execute full re-index (re-process entire document).
        
        Args:
            task: Update task
            
        Returns:
            Number of chunks created
        """
        logger.info(f"Executing full re-index for {task.file_path}")
        
        # Remove old chunks
        await self.vector_store.remove_document_chunks(task.file_path)
        
        # Extract text
        text = await self.text_extractor.extract_text_async(task.file_path)
        if not text or not text.strip():
            raise ValueError(f"No text extracted from {task.file_path}")
        
        # Create chunks
        chunks = self.chunker.create_chunks(text, task.file_path)
        
        # Generate embeddings
        embeddings = self.embedding_service.encode_texts([chunk.text for chunk in chunks])
        
        # Insert chunks
        await self.vector_store.batch_insert_chunks(chunks, embeddings)
        
        # Update BM25
        bm25_documents = [
            {
                'id': f"{chunk.file_path}:{chunk.chunk_id}",
                'text': chunk.text,
                'metadata': {
                    'file_path': chunk.file_path,
                    'chunk_id': chunk.chunk_id
                }
            }
            for chunk in chunks
        ]
        self.bm25_service.add_documents(bm25_documents)
        
        # Update database
        from ..extraction.file_validator import FileValidator
        file_validator = FileValidator()
        file_metadata = file_validator.extract_file_metadata(task.file_path)
        file_hash = file_validator.calculate_file_hash(task.file_path)
        
        await self.database_service.store_document_metadata(
            file_path=task.file_path,
            file_hash=file_hash,
            file_type=file_metadata["file_type"],
            file_size=file_metadata["size_bytes"],
            last_modified=file_metadata["modified_at"],
            content_preview=text[:500],
            chunks_count=len(chunks),
            processing_status="indexed"
        )
        
        logger.info(f"Full re-index completed: {len(chunks)} chunks")
        return len(chunks)
    
    async def _execute_chunk_update(
        self,
        task: UpdateTask,
        diff_result: ChunkDiffResult
    ) -> int:
        """
        Execute chunk-level update (only update changed chunks).
        
        Args:
            task: Update task
            diff_result: Chunk diff result
            
        Returns:
            Number of chunks updated
        """
        logger.info(f"Executing chunk update for {task.file_path}")
        
        if not diff_result:
            # Fallback to full re-index if no diff result
            logger.warning(f"No diff result provided, falling back to full re-index")
            return await self._execute_full_reindex(task)
        
        chunks_updated = 0
        
        # 1. Remove removed chunks
        for removed_chunk in diff_result.removed_chunks:
            # Remove from vector store (by chunk ID)
            # Note: Vector store removes by file_path, so we need to remove all and re-add unchanged
            pass  # Will handle in step 3
        
        # 2. Update modified chunks
        for match in diff_result.modified_chunks:
            # Remove old chunk
            # Note: Vector store doesn't support removing individual chunks easily
            # So we'll remove all and re-add unchanged + new
            pass  # Will handle in step 3
        
        # 3. Remove all chunks, then re-add unchanged + modified + added
        await self.vector_store.remove_document_chunks(task.file_path)
        
        # Re-add unchanged chunks (no re-embedding needed, but we need to store embeddings)
        # For simplicity, we'll re-embed everything (optimization: store embeddings in checkpoint)
        all_chunks_to_add = []
        
        # Unchanged chunks (re-add with same embeddings)
        for match in diff_result.unchanged_chunks:
            all_chunks_to_add.append(match.new_chunk)
        
        # Modified chunks (re-process)
        for match in diff_result.modified_chunks:
            all_chunks_to_add.append(match.new_chunk)
        
        # Added chunks
        for added_chunk in diff_result.added_chunks:
            all_chunks_to_add.append(added_chunk)
        
        # Generate embeddings for all chunks
        embeddings = self.embedding_service.encode_texts([chunk.text for chunk in all_chunks_to_add])
        
        # Insert all chunks
        await self.vector_store.batch_insert_chunks(all_chunks_to_add, embeddings)
        chunks_updated = len(all_chunks_to_add)
        
        # Update BM25
        bm25_documents = [
            {
                'id': f"{chunk.file_path}:{chunk.chunk_id}",
                'text': chunk.text,
                'metadata': {
                    'file_path': chunk.file_path,
                    'chunk_id': chunk.chunk_id
                }
            }
            for chunk in all_chunks_to_add
        ]
        self.bm25_service.add_documents(bm25_documents)
        
        # Update database
        from ..extraction.file_validator import FileValidator
        file_validator = FileValidator()
        file_metadata = file_validator.extract_file_metadata(task.file_path)
        file_hash = file_validator.calculate_file_hash(task.file_path)
        
        await self.database_service.store_document_metadata(
            file_path=task.file_path,
            file_hash=file_hash,
            file_type=file_metadata["file_type"],
            file_size=file_metadata["size_bytes"],
            last_modified=file_metadata["modified_at"],
            content_preview=all_chunks_to_add[0].text[:500] if all_chunks_to_add else "",
            chunks_count=len(all_chunks_to_add),
            processing_status="indexed"
        )
        
        logger.info(f"Chunk update completed: {chunks_updated} chunks")
        return chunks_updated
    
    async def _execute_smart_hybrid(
        self,
        task: UpdateTask,
        diff_result: ChunkDiffResult
    ) -> int:
        """
        Execute smart hybrid update (update changed, verify unchanged).
        
        Args:
            task: Update task
            diff_result: Chunk diff result
            
        Returns:
            Number of chunks updated
        """
        logger.info(f"Executing smart hybrid update for {task.file_path}")
        
        # Similar to chunk update, but with verification step
        # For now, same as chunk update (verification can be added later)
        return await self._execute_chunk_update(task, diff_result)
    
    async def _verify_update(self, file_path: str):
        """
        Verify that update was successful.
        
        Args:
            file_path: Path to file
            
        Raises:
            Exception if verification fails
        """
        logger.debug(f"Verifying update for {file_path}")
        
        # Check that chunks exist in vector store
        chunks_data = self.vector_store.get_document_chunks(file_path)
        if not chunks_data or not chunks_data.get('ids'):
            raise ValueError(f"No chunks found in vector store for {file_path} after update")
        
        # Check that metadata exists in database
        from database.database import get_db
        from database.models import IndexedDocument
        from sqlalchemy import select
        
        async for db_session in get_db():
            stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
            result = await db_session.execute(stmt)
            doc = result.scalar_one_or_none()
            if not doc:
                raise ValueError(f"No metadata found in database for {file_path} after update")
            if doc.processing_status != "indexed":
                raise ValueError(f"Document status is {doc.processing_status}, expected 'indexed'")
            break
        
        logger.debug(f"Update verification passed for {file_path}")

