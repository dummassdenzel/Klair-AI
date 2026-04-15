"""
IndexingService — owns the full file-ingestion pipeline.

Responsibilities:
- Accept a directory, scan files, build the metadata index, and run background
  content indexing (chunking + embedding + ChromaDB + BM25 + SQLite).
- Handle incremental updates: add, remove, and enqueue file changes.
- Maintain the FilenameTrie (shared with RetrievalService via reference) and the
  bounded LRU metadata cache.

The orchestrator constructs this service and delegates all indexing calls to it.
"""

import asyncio
import logging
import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import ProcessingResult
from .extraction.text_extractor import TextExtractor
from .extraction.chunker import DocumentChunker
from .extraction.embedding_service import EmbeddingService
from .extraction.file_validator import FileValidator
from .storage.vector_store import VectorStoreService
from .storage.bm25_service import BM25Service
from .retrieval.filename_trie import FilenameTrie
from .updates.update_queue import UpdateQueue
from .updates.update_executor import UpdateExecutor
from .updates.update_worker import UpdateWorker
from .updates.chunk_differ import ChunkDiffer
from .updates.update_strategy import UpdateStrategySelector
from database import DatabaseService


logger = logging.getLogger(__name__)

DEFAULT_METADATA_CACHE_MAX_SIZE = 2000


class MetadataCache:
    """
    Bounded LRU in-memory cache mapping file_path → (hash, metadata_dict).
    Evicts the least-recently-used entry when the max size is reached.
    The DB is always the source of truth; this cache only accelerates hot reads.
    """

    def __init__(self, max_size: int = DEFAULT_METADATA_CACHE_MAX_SIZE):
        self.max_size = max_size
        self._cache: OrderedDict = OrderedDict()

    def get(self, file_path: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        if file_path not in self._cache:
            return None
        self._cache.move_to_end(file_path)
        return self._cache[file_path]

    def set(self, file_path: str, hash_val: str, metadata: Dict[str, Any]) -> None:
        if file_path in self._cache:
            self._cache.move_to_end(file_path)
        self._cache[file_path] = (hash_val, metadata)
        if len(self._cache) > self.max_size:
            self._cache.popitem(last=False)

    def remove(self, file_path: str) -> None:
        self._cache.pop(file_path, None)

    def clear(self) -> None:
        self._cache.clear()

    def __contains__(self, file_path: str) -> bool:
        return file_path in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def keys(self):
        return self._cache.keys()


class IndexingService:
    """
    Owns the entire file-ingestion pipeline: scan → chunk → embed → store.

    The FilenameTrie instance is created here and shared with RetrievalService
    via a direct object reference so both services see live updates without any
    additional synchronisation.
    """

    def __init__(
        self,
        text_extractor: TextExtractor,
        file_validator: FileValidator,
        chunker: DocumentChunker,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        bm25_service: BM25Service,
        database_service: DatabaseService,
        update_queue: UpdateQueue,
        update_executor: UpdateExecutor,
        update_worker: UpdateWorker,
        chunk_differ: ChunkDiffer,
        strategy_selector: UpdateStrategySelector,
    ) -> None:
        self.text_extractor = text_extractor
        self.file_validator = file_validator
        self.chunker = chunker
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.bm25_service = bm25_service
        self.database_service = database_service
        self.update_queue = update_queue
        self.update_executor = update_executor
        self.update_worker = update_worker
        self.chunk_differ = chunk_differ
        self.strategy_selector = strategy_selector

        # Shared with RetrievalService (passed by reference)
        self.filename_trie = FilenameTrie()

        # Bounded LRU cache; DB is source of truth
        self._metadata_cache = MetadataCache(max_size=DEFAULT_METADATA_CACHE_MAX_SIZE)

        # Mutable state
        self.current_directory: Optional[str] = None
        self.is_initializing: bool = False
        self.files_being_processed: set = set()
        self._indexing_task: Optional[asyncio.Task] = None
        self._shutdown: bool = False
        self._post_index_hook = None

    # ------------------------------------------------------------------
    # Hook registration
    # ------------------------------------------------------------------

    def set_post_index_hook(self, hook) -> None:
        """Register a no-arg callable invoked once when background content indexing completes."""
        self._post_index_hook = hook

    # ------------------------------------------------------------------
    # Background task startup
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """
        Start background initialization tasks.

        Must be called from an async context AFTER any data-clearing operations
        (clear_all_data) so _load_existing_metadata reads the DB in its correct
        final state.
        """
        asyncio.create_task(self._load_existing_metadata())
        asyncio.create_task(self.update_worker.start())
        logger.debug("IndexingService background tasks started (metadata loader + update worker)")

    # ------------------------------------------------------------------
    # Directory scanning and metadata indexing
    # ------------------------------------------------------------------

    async def initialize_from_directory(
        self, directory_path: str, resume_mode: bool = False
    ) -> None:
        """
        Initialize processor with documents from directory using metadata-first indexing.

        Args:
            directory_path: Absolute path to the folder to index.
            resume_mode: When True, already-indexed unchanged files are skipped so
                the existing BM25 pickle stays valid and only new/changed files are
                re-processed.
        """
        start_time = asyncio.get_event_loop().time()

        try:
            dir_path = Path(directory_path)
            if not dir_path.exists():
                raise ValueError(f"Directory does not exist: {directory_path}")
            if not dir_path.is_dir():
                raise ValueError(f"Path is not a directory: {directory_path}")

            if self.is_initializing:
                logger.warning("Already initializing directory, skipping duplicate initialization")
                return

            if self.current_directory == directory_path and self.filename_trie.file_count > 0:
                logger.info(
                    f"Directory {directory_path} already initialized with "
                    f"{self.filename_trie.file_count} files, skipping re-initialization"
                )
                return

            logger.info(
                f"Initializing from directory: {directory_path}"
                + (" (resume mode — skipping unchanged files)" if resume_mode else "")
            )
            self.current_directory = directory_path
            self.is_initializing = True

            metadata_start = asyncio.get_event_loop().time()
            metadata_files = await self._build_metadata_index(
                directory_path, resume_mode=resume_mode
            )
            metadata_elapsed = asyncio.get_event_loop().time() - metadata_start

            if not metadata_files:
                if resume_mode:
                    logger.info(
                        f"Resume mode: all files in {directory_path} are already indexed and unchanged"
                    )
                else:
                    logger.warning(f"No supported files found in {directory_path}")
                self.is_initializing = False
                return

            logger.info(f"Metadata index built: {len(metadata_files)} files in {metadata_elapsed:.2f}s")
            logger.info("Files are now queryable by filename/metadata")

            logger.info(f"Starting background content indexing for {len(metadata_files)} files...")
            self._shutdown = False
            self._indexing_task = asyncio.create_task(
                self._index_content_background(metadata_files, directory_path)
            )

            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"Initialization complete: {len(metadata_files)} files queued in {elapsed:.2f}s")
            logger.info("Content indexing running in background (non-blocking)")

            self.is_initializing = False
            logger.debug("Initialization flag cleared, file monitor events now enabled")

        except Exception as e:
            logger.error(f"Failed to initialize from directory: {e}")
            self.is_initializing = False
            raise

    async def _build_metadata_index(
        self, directory_path: str, resume_mode: bool = False
    ) -> List[str]:
        """
        Build metadata index quickly (< 1 second for most directories).
        Stores file metadata in database immediately, allowing filename queries.
        Returns list of file paths that need content indexing.

        In resume_mode, files that are already fully indexed and whose mtime has not
        changed are added to the trie but excluded from the returned list.
        """
        dir_path = Path(directory_path)
        supported_files = []

        existing_docs: Dict[str, Any] = {}
        if resume_mode:
            existing_docs = await self.database_service.get_indexed_docs_for_directory(
                directory_path
            )
            logger.info(
                f"Resume mode: {len(existing_docs)} existing indexed documents found in DB"
            )

        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue

            is_valid, error = self.file_validator.validate_file(str(file_path))
            if not is_valid:
                continue

            fp_str = str(file_path)
            filename = file_path.name

            if resume_mode and fp_str in existing_docs:
                existing = existing_docs[fp_str]
                if existing.get("processing_status") == "indexed":
                    try:
                        disk_mtime = file_path.stat().st_mtime
                        db_mtime = existing.get("last_modified")
                        if db_mtime is not None:
                            if hasattr(db_mtime, "timestamp"):
                                db_ts = db_mtime.timestamp()
                            else:
                                db_ts = float(db_mtime)
                            if abs(disk_mtime - db_ts) < 2.0:
                                self.filename_trie.add(filename, fp_str)
                                meta = {
                                    "file_type": existing.get("file_type", ""),
                                    "size_bytes": existing.get("file_size", 0),
                                    "modified_at": db_mtime,
                                    "chunks": existing.get("chunks_count", 0),
                                    "processing_status": "indexed",
                                }
                                if len(self._metadata_cache) < self._metadata_cache.max_size:
                                    self._metadata_cache.set(
                                        fp_str, existing.get("file_hash", ""), meta
                                    )
                                continue
                    except Exception:
                        pass

            try:
                file_metadata = self.file_validator.extract_file_metadata(fp_str)
                file_type = file_metadata.get("file_type", "unknown")
                file_size = file_metadata.get("size_bytes", 0)
                last_modified = file_metadata.get("modified_at")

                await self.database_service.store_document_metadata(
                    file_path=fp_str,
                    file_hash="",
                    file_type=file_type,
                    file_size=file_size,
                    last_modified=last_modified,
                    content_preview="",
                    chunks_count=0,
                    processing_status="metadata_only",
                )

                self.filename_trie.add(filename, fp_str)
                meta = {
                    "file_type": file_type,
                    "size_bytes": file_size,
                    "modified_at": last_modified,
                    "chunks": 0,
                    "processing_status": "metadata_only",
                }
                if len(self._metadata_cache) < self._metadata_cache.max_size:
                    self._metadata_cache.set(fp_str, "", meta)

                supported_files.append(fp_str)

            except Exception as e:
                logger.warning(f"Could not index metadata for {fp_str}: {e}")
                continue

        return supported_files

    async def _index_content_background(
        self, file_paths: List[str], directory_path: str
    ) -> None:
        """
        Background content indexing. Processes files in batches without blocking.
        Updates documents from 'metadata_only' to 'indexed' status.
        Exits early if _shutdown is set (e.g. user switched to another directory).
        """
        from config import settings

        logger.info(f"Background content indexing started for {len(file_paths)} files")
        batch_size = settings.BATCH_SIZE
        processed = 0
        failed = 0
        try:
            for i in range(0, len(file_paths), batch_size):
                if self._shutdown:
                    logger.info("Background content indexing cancelled (directory was changed)")
                    return
                batch = file_paths[i:i + batch_size]
                tasks = [self._process_single_file(file_path) for file_path in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        failed += 1
                        logger.error(f"Background indexing failed: {result}")
                    else:
                        processed += 1
                await asyncio.to_thread(self.bm25_service.save)
                if (i + batch_size) % 50 == 0 or i + batch_size >= len(file_paths):
                    logger.info(
                        f"Background indexing progress: {processed + failed}/{len(file_paths)} files "
                        f"({processed} indexed, {failed} failed)"
                    )
                if i + batch_size < len(file_paths):
                    await asyncio.sleep(0.1)
            logger.info(
                f"Background content indexing complete: {processed} indexed, {failed} failed"
            )
        except asyncio.CancelledError:
            logger.info("Background content indexing task was cancelled")
            try:
                await asyncio.to_thread(self.bm25_service.save)
            except Exception:
                pass
            raise
        except Exception as e:
            logger.error(f"Background content indexing error: {e}")
        finally:
            self._indexing_task = None
            if not self._shutdown and file_paths and processed > 0:
                try:
                    n = await self.database_service.set_documents_indexed(file_paths)
                    if n:
                        logger.debug(
                            f"Synced {n} document(s) to indexed status for search consistency"
                        )
                except Exception as e:
                    logger.warning(f"Final sync of indexed status failed: {e}")
            if not self._shutdown and self._post_index_hook is not None:
                try:
                    self._post_index_hook()
                except Exception as e:
                    logger.warning(f"Post-index hook failed: {e}")

    async def _process_single_file(self, file_path: str) -> ProcessingResult:
        """Process a single file (used in batch processing)."""
        start_time = asyncio.get_event_loop().time()
        try:
            await self.add_document(file_path, use_queue=False)
            processing_time = asyncio.get_event_loop().time() - start_time
            return ProcessingResult(
                success=True,
                file_path=file_path,
                chunks_created=0,
                processing_time=processing_time,
            )
        except Exception as e:
            processing_time = asyncio.get_event_loop().time() - start_time
            logger.error(f"Failed to process {file_path}: {e}")
            return ProcessingResult(
                success=False,
                file_path=file_path,
                chunks_created=0,
                error_message=str(e),
                processing_time=processing_time,
            )

    # ------------------------------------------------------------------
    # Document CRUD
    # ------------------------------------------------------------------

    async def enqueue_update(
        self,
        file_path: str,
        update_type: str = "modified",
        user_requested: bool = False,
    ) -> bool:
        """Enqueue a document update to the priority queue."""
        try:
            file_metadata = self.file_validator.extract_file_metadata(file_path)
            file_size_bytes = file_metadata.get("size_bytes", 0)
            last_queried = file_metadata.get("modified_at") or datetime.now(timezone.utc)
            success = await self.update_queue.enqueue(
                file_path=file_path,
                update_type=update_type,
                file_size_bytes=file_size_bytes,
                last_queried=last_queried,
                is_in_active_session=False,
                user_requested=user_requested,
            )
            if success:
                logger.info(f"Enqueued update for {file_path} (type: {update_type})")
            else:
                logger.warning(f"Failed to enqueue update for {file_path} (queue may be full)")
            return success
        except Exception as e:
            logger.error(f"Error enqueueing update for {file_path}: {e}")
            return False

    async def add_document(
        self,
        file_path: str,
        force_reindex: bool = False,
        use_queue: bool = True,
    ) -> None:
        """
        Add or update a document with incremental indexing.

        Args:
            file_path: Path to the file to index.
            force_reindex: If True, re-index even if the file hasn't changed.
            use_queue: If True, use update queue (incremental updates).
                       If False, process directly (initial indexing).
        """
        if use_queue:
            current_hash = self.file_validator.calculate_file_hash(file_path)
            stored_hash, _ = await self._get_cached_or_db_hash_metadata(file_path)
            if not force_reindex and stored_hash and stored_hash == current_hash:
                logger.debug(f"File {file_path} unchanged, skipping update")
                return
            await self.enqueue_update(file_path, update_type="modified")
            return

        if file_path in self.files_being_processed:
            logger.debug(f"File {file_path} is already being processed, skipping duplicate")
            return

        self.files_being_processed.add(file_path)

        try:
            file_metadata = self.file_validator.extract_file_metadata(file_path)
            current_hash = self.file_validator.calculate_file_hash(file_path)

            stored_hash, _ = await self._get_cached_or_db_hash_metadata(file_path)
            if not force_reindex and stored_hash and stored_hash == current_hash:
                logger.debug(f"File {file_path} unchanged, skipping re-index")
                self.files_being_processed.discard(file_path)
                return

            from database.database import AsyncSessionLocal
            from database.models import IndexedDocument
            from sqlalchemy import select

            async with AsyncSessionLocal() as db_session:
                stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
                result = await db_session.execute(stmt)
                existing_doc = result.scalar_one_or_none()

                if (
                    existing_doc
                    and existing_doc.processing_status == "indexed"
                    and existing_doc.file_hash == current_hash
                ):
                    if not force_reindex:
                        logger.debug(f"File {file_path} already fully indexed, skipping")
                    self._metadata_cache.set(file_path, current_hash, file_metadata)
                    self.files_being_processed.discard(file_path)
                    return

            if stored_hash and stored_hash != current_hash:
                logger.info(f"File {file_path} changed, removing old chunks")
                await self.vector_store.remove_document_chunks(file_path)
                removed = self.bm25_service.remove_file_chunks(file_path)
                if removed:
                    logger.debug(f"Removed {removed} stale BM25 chunks for {file_path}")

            text = await self.text_extractor.extract_text_async(file_path)
            if not text or not text.strip():
                logger.warning(f"No text extracted from {file_path}")
                await self.database_service.store_document_metadata(
                    file_path=file_path,
                    file_hash=current_hash,
                    file_type=file_metadata["file_type"],
                    file_size=file_metadata["size_bytes"],
                    last_modified=file_metadata["modified_at"],
                    content_preview="",
                    chunks_count=0,
                    processing_status="error",
                )
                self.files_being_processed.discard(file_path)
                return

            chunks = self.chunker.create_chunks(text, file_path)
            content_preview = text[:500]
            embeddings = self.embedding_service.encode_texts([chunk.text for chunk in chunks])

            # Lazily wire the embedding tokenizer into the chunker on first successful
            # encode call so subsequent chunks use accurate token counts.
            if self.chunker._tokenizer is None:
                tok = getattr(getattr(self.embedding_service, "embed_model", None), "tokenizer", None)
                if tok is not None:
                    self.chunker.set_tokenizer(tok)

            await self.vector_store.batch_insert_chunks(chunks, embeddings)
            bm25_documents = [
                {
                    "id": f"{chunk.file_path}:{chunk.chunk_id}",
                    "text": chunk.text,
                    "metadata": {
                        "file_path": chunk.file_path,
                        "chunk_id": chunk.chunk_id,
                        "file_type": file_metadata["file_type"],
                    },
                }
                for chunk in chunks
            ]
            self.bm25_service.add_documents(bm25_documents)
            logger.debug(f"Added {len(chunks)} chunks to BM25 index for {file_path}")

            await self.database_service.store_document_metadata(
                file_path=file_path,
                file_hash=current_hash,
                file_type=file_metadata["file_type"],
                file_size=file_metadata["size_bytes"],
                last_modified=file_metadata["modified_at"],
                content_preview=content_preview,
                chunks_count=len(chunks),
                processing_status="indexed",
            )

            self._metadata_cache.set(file_path, current_hash, file_metadata)

        except Exception as e:
            logger.error(f"Error processing document {file_path}: {e}")
            try:
                await self.database_service.store_document_metadata(
                    file_path=file_path,
                    file_hash="",
                    file_type=Path(file_path).suffix.lower(),
                    file_size=0,
                    last_modified=datetime.now(timezone.utc),
                    content_preview="",
                    chunks_count=0,
                    processing_status="error",
                )
            except Exception:
                pass
            raise
        finally:
            self.files_being_processed.discard(file_path)

    async def remove_document(self, file_path: str) -> None:
        """Remove document and clean up tracking."""
        try:
            await self.vector_store.remove_document_chunks(file_path)
            filename = Path(file_path).name
            self.filename_trie.remove(filename, file_path)
            self._metadata_cache.remove(file_path)
            logger.info(f"Removed document: {file_path}")
        except Exception as e:
            logger.error(f"Error removing document {file_path}: {e}")

    async def cancel_background_work(self) -> None:
        """
        Cancel in-flight background content indexing (e.g. when user switches directory).
        Prevents the old indexer from writing to the DB after the new one has cleared it.
        """
        self._shutdown = True
        if self._indexing_task and not self._indexing_task.done():
            self._indexing_task.cancel()
            try:
                await self._indexing_task
            except asyncio.CancelledError:
                pass
        self._indexing_task = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_existing_metadata(self) -> None:
        """Load existing documents: rebuild trie for all, fill LRU cache up to max_size."""
        try:
            from database.database import AsyncSessionLocal
            from database.models import IndexedDocument
            from sqlalchemy import select

            async with AsyncSessionLocal() as db_session:
                stmt = select(IndexedDocument).where(
                    IndexedDocument.processing_status.in_(["indexed", "metadata_only"])
                )
                result = await db_session.execute(stmt)
                docs = result.scalars().all()

                for doc in docs:
                    filename = Path(doc.file_path).name
                    self.filename_trie.add(filename, doc.file_path)
                    if len(self._metadata_cache) < self._metadata_cache.max_size:
                        meta = {
                            "file_type": doc.file_type,
                            "size_bytes": doc.file_size,
                            "modified_at": doc.last_modified,
                            "chunks": doc.chunks_count,
                            "processing_status": doc.processing_status,
                        }
                        self._metadata_cache.set(doc.file_path, doc.file_hash or "", meta)

            indexed_count = sum(1 for d in docs if d.processing_status == "indexed")
            metadata_only_count = sum(1 for d in docs if d.processing_status == "metadata_only")
            logger.info(
                f"Loaded {len(docs)} documents (trie); cache has {len(self._metadata_cache)} entries "
                f"({indexed_count} indexed, {metadata_only_count} metadata-only)"
            )
        except Exception as e:
            logger.warning(f"Could not load existing metadata: {e}")

    async def _get_cached_or_db_hash_metadata(
        self, file_path: str
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Return (stored_hash, stored_metadata) from LRU cache or DB. Caches DB result."""
        cached = self._metadata_cache.get(file_path)
        if cached is not None:
            return cached[0], cached[1]
        doc = await self.database_service.get_document_by_path(file_path)
        if doc is None:
            return None, None
        meta = {
            "file_type": doc.file_type,
            "size_bytes": doc.file_size,
            "modified_at": doc.last_modified,
            "chunks": doc.chunks_count,
            "processing_status": doc.processing_status,
        }
        self._metadata_cache.set(file_path, doc.file_hash or "", meta)
        return doc.file_hash, meta
