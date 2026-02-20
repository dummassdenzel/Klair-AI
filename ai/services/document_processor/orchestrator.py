import asyncio
import logging
import os
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple, Any, AsyncIterator
from datetime import datetime
from pathlib import Path

from .models import QueryResult, ProcessingResult, FileMetadata
from .extraction.text_extractor import TextExtractor
from .extraction.chunker import DocumentChunker
from .extraction.embedding_service import EmbeddingService
from .storage.vector_store import VectorStoreService
from .llm.llm_service import LLMService
from .extraction.file_validator import FileValidator
from .extraction.ocr_service import OCRService
from .storage.bm25_service import BM25Service
from .retrieval.hybrid_search import HybridSearchService
from .retrieval.reranker_service import ReRankingService
from .retrieval.filename_trie import FilenameTrie
from .updates.update_queue import UpdateQueue, UpdateTask, UpdatePriority
from .updates.update_executor import UpdateExecutor
from .updates.update_worker import UpdateWorker
from .updates.chunk_differ import ChunkDiffer
from .updates.update_strategy import UpdateStrategySelector
from .query_config import RetrievalConfig, default_retrieval_config, is_aggregation_query
from database import DatabaseService
from ..routing import Router, QueryClassifier, Route


logger = logging.getLogger(__name__)

# Default max size for metadata cache (prevents unbounded memory with 1000+ files)
DEFAULT_METADATA_CACHE_MAX_SIZE = 2000


class MetadataCache:
    """
    Bounded LRU cache for file_path -> (hash, metadata).
    Prevents unbounded memory growth; DB is source of truth on miss.
    """
    __slots__ = ("_cache", "max_size")

    def __init__(self, max_size: int = DEFAULT_METADATA_CACHE_MAX_SIZE):
        self.max_size = max(1, max_size)
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    def get(self, file_path: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Return (hash, metadata) or None. Moves entry to end (LRU)."""
        if file_path not in self._cache:
            return None
        self._cache.move_to_end(file_path)
        entry = self._cache[file_path]
        return entry["hash"], entry["metadata"]

    def set(self, file_path: str, hash_val: str, metadata: Dict[str, Any]) -> None:
        """Set or update entry. Evicts oldest if at capacity."""
        if file_path in self._cache:
            self._cache.move_to_end(file_path)
            self._cache[file_path] = {"hash": hash_val, "metadata": metadata}
            return
        while len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
        self._cache[file_path] = {"hash": hash_val, "metadata": metadata}

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


class DocumentProcessorOrchestrator:
    """Main orchestrator that coordinates all document processing services"""
    
    def __init__(self, 
                 persist_dir: str = "./chroma_db",
                 embed_model_name: str = "BAAI/bge-small-en-v1.5",
                 max_file_size_mb: int = 50,
                 chunk_size: int = 1000,
                 chunk_overlap: int = 200,
                 ollama_base_url: str = "http://localhost:11434",
                 ollama_model: str = "tinyllama",
                 gemini_api_key: Optional[str] = None,
                 gemini_model: str = "gemini-2.5-pro",
                 groq_api_key: Optional[str] = None,
                 groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
                 llm_provider: str = "ollama"):
        
        # Initialize OCR service (optional, for scanned documents and images)
        # Try to import settings, but use defaults if not available
        try:
            import sys
            from pathlib import Path
            # Add ai directory to path if not already there
            ai_dir = Path(__file__).parent.parent.parent.parent
            if str(ai_dir) not in sys.path:
                sys.path.insert(0, str(ai_dir))
            from config import settings
            
            ocr_service = OCRService(
                tesseract_path=settings.TESSERACT_PATH if settings.TESSERACT_PATH else None,
                cache_dir=settings.OCR_CACHE_DIR,
                languages=settings.OCR_LANGUAGES,
                ocr_timeout=getattr(settings, "OCR_TIMEOUT", 300),
            )
        except (ImportError, AttributeError):
            logger.info("OCR settings not available, using defaults")
            ocr_service = OCRService()
        
        # Initialize all services
        self.text_extractor = TextExtractor(ocr_service=ocr_service)
        self.chunker = DocumentChunker(chunk_size, chunk_overlap)
        self.embedding_service = EmbeddingService(embed_model_name)
        self.vector_store = VectorStoreService(persist_dir)
        # LLM service now supports provider switch (ollama | gemini)
        self.llm_service = LLMService(
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            groq_api_key=groq_api_key,
            groq_model=groq_model,
            provider=llm_provider
        )
        self.file_validator = FileValidator(max_file_size_mb, ocr_service=ocr_service)
        self.database_service = DatabaseService()
        
        # Hybrid search services (semantic + keyword)
        self.bm25_service = BM25Service(persist_dir)
        self.hybrid_search = HybridSearchService(k=60)  # RRF constant
        
        # Re-ranking service (cross-encoder for improved relevance)
        self.reranker = ReRankingService(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
        
        # Filename Trie for fast O(m) filename search
        self.filename_trie = FilenameTrie()
        
        # Retrieval configuration
        self.retrieval_config = default_retrieval_config

        # Agentic routing: classification + route resolution
        self.router = Router(QueryClassifier(self.llm_service))
        
        # Phase 3: Incremental Updates components
        self.update_queue = UpdateQueue(max_queue_size=1000)
        self.chunk_differ = ChunkDiffer(self.embedding_service)
        self.strategy_selector = UpdateStrategySelector()
        self.update_executor = UpdateExecutor(
            vector_store=self.vector_store,
            bm25_service=self.bm25_service,
            text_extractor=self.text_extractor,
            chunker=self.chunker,
            embedding_service=self.embedding_service,
            database_service=self.database_service,
            chunk_differ=self.chunk_differ,
            file_validator=self.file_validator,
        )
        self.update_worker = UpdateWorker(
            update_queue=self.update_queue,
            update_executor=self.update_executor,
            chunk_differ=self.chunk_differ,
            strategy_selector=self.strategy_selector,
            chunker=self.chunker,
            text_extractor=self.text_extractor
        )
        
        # State tracking (bounded LRU cache; DB is source of truth)
        self._metadata_cache = MetadataCache(max_size=DEFAULT_METADATA_CACHE_MAX_SIZE)
        self.current_directory: Optional[str] = None
        self.is_initializing: bool = False  # Flag to prevent file monitor events during initial indexing
        self.files_being_processed: set = set()  # Track files currently being indexed to prevent duplicate processing
        self._indexing_task: Optional[asyncio.Task] = None  # So caller can cancel when switching directory
        self._shutdown: bool = False  # Set when directory is switched so background indexing exits
        
        logger.info("DocumentProcessorOrchestrator initialized with hybrid search (semantic + keyword) and incremental updates")
        
        # Load existing indexed documents into memory
        asyncio.create_task(self._load_existing_metadata())
        
        # Start update worker for incremental updates
        asyncio.create_task(self.update_worker.start())
    
    async def _load_existing_metadata(self):
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
                f"📚 Loaded {len(docs)} documents (trie); cache has {len(self._metadata_cache)} entries "
                f"({indexed_count} indexed, {metadata_only_count} metadata-only)"
            )
        except Exception as e:
            logger.warning(f"Could not load existing metadata: {e}")
    
    async def _get_cached_or_db_hash_metadata(self, file_path: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
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

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
    
    async def clear_all_data(self):
        """Clear all indexed data (vector store, BM25, and database records)"""
        logger.info("Clearing all indexed data...")
        
        # Clear update queue first to prevent processing stale updates
        if hasattr(self, 'update_queue'):
            await self.update_queue.clear()
            logger.info("Update queue cleared")
        
        # Clear vector store
        await self.vector_store.clear_collection()
        self._metadata_cache.clear()
        self.files_being_processed.clear()
        logger.info("Vector store cleared")
        
        # Clear BM25 index
        self.bm25_service.clear()
        logger.info("BM25 index cleared")
        
        # Clear Filename Trie
        self.filename_trie.clear()
        logger.info("Filename Trie cleared")

        self.router.clear_cache()
        
        # Clear database records
        try:
            from database.database import AsyncSessionLocal
            from database.models import IndexedDocument
            from sqlalchemy import delete
            
            async with AsyncSessionLocal() as session:
                try:
                    stmt = delete(IndexedDocument)
                    await session.execute(stmt)
                    await session.commit()
                    logger.info("Database document index records cleared")
                except Exception:
                    await session.rollback()
                    raise
        except Exception as e:
            logger.warning(f"Failed to clear database records: {e}")

    async def cancel_background_work(self) -> None:
        """
        Cancel in-flight background content indexing (e.g. when user switches directory).
        Prevents the old orchestrator from writing to the DB after the new one has cleared it.
        """
        self._shutdown = True
        if self._indexing_task and not self._indexing_task.done():
            self._indexing_task.cancel()
            try:
                await self._indexing_task
            except asyncio.CancelledError:
                pass
        self._indexing_task = None
    
    async def initialize_from_directory(self, directory_path: str):
        """Initialize processor with documents from directory using metadata-first indexing"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            dir_path = Path(directory_path)
            if not dir_path.exists():
                raise ValueError(f"Directory does not exist: {directory_path}")
            
            if not dir_path.is_dir():
                raise ValueError(f"Path is not a directory: {directory_path}")
            
            # Check if already initializing or already initialized for this directory
            if self.is_initializing:
                logger.warning(f"Already initializing directory, skipping duplicate initialization")
                return
            
            if self.current_directory == directory_path and self.filename_trie.file_count > 0:
                logger.info(f"Directory {directory_path} already initialized with {self.filename_trie.file_count} files, skipping re-initialization")
                return
            
            logger.info(f"Initializing from directory: {directory_path}")
            self.current_directory = directory_path
            self.is_initializing = True  # Set flag to prevent file monitor events
            
            # PHASE 1: Build metadata index (FAST - < 1 second for most directories)
            metadata_start = asyncio.get_event_loop().time()
            metadata_files = await self._build_metadata_index(directory_path)
            metadata_elapsed = asyncio.get_event_loop().time() - metadata_start
            
            if not metadata_files:
                logger.warning(f"No supported files found in {directory_path}")
                return
            
            logger.info(f"✅ Metadata index built: {len(metadata_files)} files in {metadata_elapsed:.2f}s")
            logger.info(f"📁 Files are now queryable by filename/metadata")
            
            # PHASE 2: Background content indexing (non-blocking)
            logger.info(f"🔄 Starting background content indexing for {len(metadata_files)} files...")
            self._shutdown = False
            self._indexing_task = asyncio.create_task(
                self._index_content_background(metadata_files, directory_path)
            )
            
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"Initialization complete: {len(metadata_files)} files metadata-indexed in {elapsed:.2f}s")
            logger.info(f"Content indexing running in background (non-blocking)")
            
            # Clear initialization flag after metadata indexing completes
            # File monitor can now process events (content indexing happens in background)
            self.is_initializing = False
            logger.debug("Initialization flag cleared, file monitor events now enabled")
            
        except Exception as e:
            logger.error(f"Failed to initialize from directory: {e}")
            # Clear flag even on error
            self.is_initializing = False
            raise
    
    async def _build_metadata_index(self, directory_path: str) -> List[str]:
        """
        Build metadata index quickly (< 1 second for most directories).
        Stores file metadata in database immediately, allowing filename queries.
        Returns list of file paths that need content indexing.
        """
        dir_path = Path(directory_path)
        supported_files = []
        
        # Fast scan: only check file existence and basic metadata
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            
            # Quick validation (no hash calculation yet - that's expensive)
            is_valid, error = self.file_validator.validate_file(str(file_path))
            if not is_valid:
                if error and "Unsupported file type" not in error:
                    logger.debug(f"Skipping {file_path}: {error}")
                continue
            
            try:
                # Extract lightweight metadata (no content reading, no hashing)
                path_obj = Path(file_path)
                stat_info = path_obj.stat()
                
                # Calculate hash only for metadata (we'll recalculate during content indexing)
                # For now, use a placeholder hash based on path + mtime for quick comparison
                quick_hash = f"{file_path}:{stat_info.st_mtime}"
                
                # Store metadata immediately in database
                await self.database_service.store_metadata_only(
                    file_path=str(file_path),
                    file_hash=quick_hash,  # Placeholder, will be updated during content indexing
                    file_type=path_obj.suffix.lower(),
                    file_size=stat_info.st_size,
                    last_modified=datetime.fromtimestamp(stat_info.st_mtime)
                )
                
                # Add to Filename Trie for fast search
                filename = path_obj.name
                self.filename_trie.add(filename, str(file_path))
                
                supported_files.append(str(file_path))
                
            except Exception as e:
                logger.warning(f"Failed to index metadata for {file_path}: {e}")
                continue
        
        return supported_files
    
    async def _index_content_background(self, file_paths: List[str], directory_path: str):
        """
        Background content indexing. Processes files in batches without blocking.
        Updates documents from 'metadata_only' to 'indexed' status.
        Exits early if _shutdown is set (e.g. user switched to another directory).
        """
        logger.info(f"🔄 Background content indexing started for {len(file_paths)} files")
        batch_size = 10
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
                if (i + batch_size) % 50 == 0 or i + batch_size >= len(file_paths):
                    logger.info(f"📊 Background indexing progress: {processed + failed}/{len(file_paths)} files "
                              f"({processed} indexed, {failed} failed)")
                if i + batch_size < len(file_paths):
                    await asyncio.sleep(0.1)
            logger.info(f"✅ Background content indexing complete: {processed} indexed, {failed} failed")
        except asyncio.CancelledError:
            logger.info("Background content indexing task was cancelled")
            raise
        except Exception as e:
            logger.error(f"Background content indexing error: {e}")
        finally:
            self._indexing_task = None
            if not self._shutdown and file_paths and processed > 0:
                try:
                    n = await self.database_service.set_documents_indexed(file_paths)
                    if n:
                        logger.debug(f"Synced {n} document(s) to indexed status for search consistency")
                except Exception as e:
                    logger.warning(f"Final sync of indexed status failed: {e}")
    
    async def _process_single_file(self, file_path: str) -> ProcessingResult:
        """Process a single file (used in batch processing)"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            await self.add_document(file_path, use_queue=False)  # Initial indexing, don't use queue
            processing_time = asyncio.get_event_loop().time() - start_time
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                chunks_created=0,
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = asyncio.get_event_loop().time() - start_time
            logger.error(f"Failed to process {file_path}: {e}")
            
            return ProcessingResult(
                success=False,
                file_path=file_path,
                chunks_created=0,
                error_message=str(e),
                processing_time=processing_time
            )
    
    async def enqueue_update(
        self,
        file_path: str,
        update_type: str = "modified",
        user_requested: bool = False
    ) -> bool:
        """
        Enqueue a document update to the priority queue (Phase 3).
        
        Args:
            file_path: Path to file to update
            update_type: Type of update ("created", "modified", "deleted")
            user_requested: Whether user explicitly requested update
            
        Returns:
            True if enqueued successfully, False otherwise
        """
        try:
            # Get file metadata for priority calculation
            file_metadata = self.file_validator.extract_file_metadata(file_path)
            file_size_bytes = file_metadata.get("size_bytes", 0)
            
            last_queried = file_metadata.get("modified_at") or datetime.utcnow()
            
            # Check if in active session (simplified - can be enhanced)
            is_in_active_session = False  # TODO: Track active sessions
            
            # Enqueue with automatic priority calculation
            success = await self.update_queue.enqueue(
                file_path=file_path,
                update_type=update_type,
                file_size_bytes=file_size_bytes,
                last_queried=last_queried,
                is_in_active_session=is_in_active_session,
                user_requested=user_requested
            )
            
            if success:
                logger.info(f"Enqueued update for {file_path} (type: {update_type})")
            else:
                logger.warning(f"Failed to enqueue update for {file_path} (queue may be full)")
            
            return success
            
        except Exception as e:
            logger.error(f"Error enqueueing update for {file_path}: {e}")
            return False
    
    async def add_document(self, file_path: str, force_reindex: bool = False, use_queue: bool = True):
        """
        Add or update a document with incremental indexing.
        
        Args:
            file_path: Path to the file to index
            force_reindex: If True, re-index even if file hasn't changed
            use_queue: If True, use update queue (Phase 3). If False, process directly (for initial indexing)
        """
        # Phase 3: Use queue for updates (unless it's initial indexing)
        if use_queue:
            current_hash = self.file_validator.calculate_file_hash(file_path)
            stored_hash, _ = await self._get_cached_or_db_hash_metadata(file_path)
            
            if not force_reindex and stored_hash == current_hash:
                logger.debug(f"File {file_path} unchanged, skipping update")
                return
            
            # Enqueue update instead of processing directly
            await self.enqueue_update(file_path, update_type="modified")
            return
        
        # Direct processing (for initial indexing or when queue is disabled)
        # Prevent duplicate processing
        if file_path in self.files_being_processed:
            logger.debug(f"File {file_path} is already being processed, skipping duplicate")
            return
        
        self.files_being_processed.add(file_path)
        
        try:
            # Get real file metadata
            file_metadata = self.file_validator.extract_file_metadata(file_path)
            current_hash = self.file_validator.calculate_file_hash(file_path)
            
            # Check if file has changed (incremental update)
            stored_hash, _ = await self._get_cached_or_db_hash_metadata(file_path)
            if not force_reindex and stored_hash == current_hash:
                logger.debug(f"File {file_path} unchanged, skipping re-index")
                # Remove from processing set before returning
                self.files_being_processed.discard(file_path)
                return
            
            # Check if document exists in database and get current status
            from database.database import AsyncSessionLocal
            from database.models import IndexedDocument
            from sqlalchemy import select
            
            async with AsyncSessionLocal() as db_session:
                stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
                result = await db_session.execute(stmt)
                existing_doc = result.scalar_one_or_none()
                
                if existing_doc and existing_doc.processing_status == "indexed" and existing_doc.file_hash == current_hash:
                    if not force_reindex:
                        logger.debug(f"File {file_path} already fully indexed, skipping")
                    self._metadata_cache.set(file_path, current_hash, file_metadata)
                    self.files_being_processed.discard(file_path)
                    return
            
            # Remove old chunks if re-indexing
            if stored_hash and stored_hash != current_hash:
                logger.info(f"File {file_path} changed, removing old chunks")
                await self.vector_store.remove_document_chunks(file_path)
                # Also remove from BM25 (we'll re-add below)
                # Note: BM25 doesn't have a remove method, so we'll just re-add
            
            # Process document content...
            text = await self.text_extractor.extract_text_async(file_path)
            if not text or not text.strip():
                logger.warning(f"No text extracted from {file_path}")
                # Update status to indicate extraction failed
                await self.database_service.store_document_metadata(
                    file_path=file_path,
                    file_hash=current_hash,
                    file_type=file_metadata["file_type"],
                    file_size=file_metadata["size_bytes"],
                    last_modified=file_metadata["modified_at"],
                    content_preview="",
                    chunks_count=0,
                    processing_status="error"
                )
                # Remove from processing set before returning
                self.files_being_processed.discard(file_path)
                return
            
            chunks = self.chunker.create_chunks(text, file_path)
            content_preview = text[:500]
            embeddings = self.embedding_service.encode_texts([chunk.text for chunk in chunks])
            await self.vector_store.batch_insert_chunks(chunks, embeddings)
            bm25_documents = [
                {
                    'id': f"{chunk.file_path}:{chunk.chunk_id}",
                    'text': chunk.text,
                    'metadata': {
                        'file_path': chunk.file_path,
                        'chunk_id': chunk.chunk_id,
                        'file_type': file_metadata["file_type"]
                    }
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
            
            # Update tracking
            self._metadata_cache.set(file_path, current_hash, file_metadata)
            
        except Exception as e:
            logger.error(f"Error processing document {file_path}: {e}")
            # Update status to error
            try:
                await self.database_service.store_document_metadata(
                    file_path=file_path,
                    file_hash="",
                    file_type=Path(file_path).suffix.lower(),
                    file_size=0,
                    last_modified=datetime.utcnow(),
                    content_preview="",
                    chunks_count=0,
                    processing_status="error"
                )
            except:
                pass
            raise
        finally:
            # Always remove from processing set, even on error
            self.files_being_processed.discard(file_path)
    
    async def remove_document(self, file_path: str):
        """Remove document and clean up tracking"""
        try:
            await self.vector_store.remove_document_chunks(file_path)
            
            # Remove from Filename Trie
            filename = Path(file_path).name
            self.filename_trie.remove(filename, file_path)
            
            self._metadata_cache.remove(file_path)
            
            logger.info(f"Removed document: {file_path}")
            
        except Exception as e:
            logger.error(f"Error removing document {file_path}: {e}")
    
    def _find_explicit_filename(self, question: str) -> Optional[str]:
        """
        Simple filename detection: only for explicit filename mentions.
        
        Returns:
            Filename if explicitly mentioned (quoted or obvious pattern), None otherwise
        """
        # Check for quoted filenames
        quoted = re.findall(r'"([^"]+)"', question)
        if quoted:
            return quoted[0]
        
        # Check for obvious filename patterns (e.g., "sales_report.pdf", "TCO005")
        filename_pattern = re.search(r'\b([A-Z][A-Z0-9_-]+\.(pdf|docx|txt|xlsx|pptx)|[A-Z][A-Z0-9]{2,})\b', question)
        if filename_pattern:
            return filename_pattern.group(1)
        
        return None
    
    async def _select_relevant_files(self, question: str) -> Optional[List[str]]:
        """
        Simplified file selection: only use Trie for explicit filenames.
        For all other queries, return None and let retrieval handle relevance.
        
        Returns:
            List of file paths if explicit filename found, None otherwise
        """
        try:
            if self.filename_trie.file_count == 0:
                return None
            
            # Only check for explicit filenames (quoted or obvious patterns)
            explicit_filename = self._find_explicit_filename(question)
            if explicit_filename:
                # Search Trie for the explicit filename
                matching_files = self.filename_trie.search(explicit_filename.lower())
                if matching_files:
                    logger.info(f"✅ Found explicit filename '{explicit_filename}': {len(matching_files)} files")
                    return list(matching_files)
            
            # No explicit filename - let retrieval handle it
            logger.info("No explicit filename detected, using retrieval for relevance")
            return None
            
        except Exception as e:
            logger.error(f"File selection failed: {e}, falling back to retrieval")
            return None
    
    async def _generate_direct_response(self, question: str, response_type: str) -> str:
        """
        Generate a direct response without document retrieval.
        Used for greetings and general queries.
        """
        try:
            if response_type == 'greeting':
                prompt = f"""You are a friendly AI assistant for a document management system.

User said: "{question}"

Respond warmly and briefly (1-2 sentences). Let them know you can help with documents.

Your response:"""
            else:  # general
                prompt = f"""You are an AI assistant for a document management system.

User asked: "{question}"

Answer their question. Your capabilities:
- Search and analyze indexed documents
- Answer questions about specific files
- List and compare documents
- Find information across multiple files

Keep your response concise and helpful (2-3 sentences).

Your response:"""

            # Use generate_simple for direct responses (not the Q&A method)
            response = await self.llm_service.generate_simple(prompt, prompt_type="short_direct")
            
            return response
            
        except Exception as e:
            logger.error(f"Direct response generation failed: {e}")
            return "Hello! I'm your document assistant. I can help you search and analyze your indexed documents. What would you like to know?"

    async def _retrieve_chunks(
        self,
        query: str,
        query_type: str,
        explicit_filename: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
        is_aggregation: bool = False,
    ) -> tuple:
        """
        Single retrieval pipeline for all document queries.
        Hybrid search: semantic (ChromaDB) + keyword (BM25) with reranking.
        """
        params = self.retrieval_config.get_retrieval_params(query_type, False, is_aggregation)
        top_k = params['top_k']
        rerank_top_k = params['rerank_top_k']
        final_top_k = params['final_top_k']
        logger.info(f"Retrieval params: top_k={top_k}, rerank_top_k={rerank_top_k}, final_top_k={final_top_k}")

        if query_embedding is None:
            query_embedding = self.embedding_service.encode_single_text(query)
        semantic_task = asyncio.create_task(
            self.vector_store.search_similar(query_embedding, top_k)
        )
        bm25_task = asyncio.to_thread(self.bm25_service.search, query, top_k)
        semantic_results, bm25_results = await asyncio.gather(semantic_task, bm25_task)

        if not semantic_results['documents'] or not semantic_results['documents'][0]:
            return ([], [], [], 0, 0)
        
        # Step 2: Apply BM25 boost (results already fetched above)
        bm25_hits = set()
        for doc_id, score, meta in (bm25_results or []):
            fp = meta.get('file_path', '')
            cid = meta.get('chunk_id')
            if fp and cid is not None:
                bm25_hits.add((fp, cid))
        
        semantic_count = len(semantic_results['documents'][0]) if semantic_results['documents'] else 0
        keyword_count = len(bm25_results) if bm25_results else 0
        
        logger.info(
            f"🔍 Hybrid search: {semantic_count} semantic, {len(bm25_hits)} BM25 boosts",
            extra={'extra_fields': {
                'event_type': 'retrieval',
                'semantic_results': semantic_count,
                'keyword_results': keyword_count,
                'bm25_boosts': len(bm25_hits)
            }}
        )
        
        # Step 3: Combine semantic + BM25 boost
        documents = []
        metadatas = []
        scores = []
        
        for doc, meta, dist in zip(
            semantic_results['documents'][0],
            semantic_results['metadatas'][0],
            semantic_results['distances'][0]
        ):
            if not doc or not doc.strip():
                continue
            
            base_score = max(0.0, 1.0 - float(dist))
            fp = meta.get('file_path', '')
            cid = meta.get('chunk_id')
            
            # Apply BM25 boost
            boost = self.retrieval_config.bm25_boost if (fp, cid) in bm25_hits else 0.0
            final_score = min(1.0, base_score + boost)
            
            documents.append(doc)
            metadatas.append(meta)
            scores.append(final_score)
        
        retrieval_count = len(documents)
        
        # Guard: if we lost everything, fall back to unboosted semantic
        if not documents:
            documents = semantic_results['documents'][0]
            metadatas = semantic_results['metadatas'][0]
            scores = [max(0.0, 1.0 - float(d)) for d in semantic_results['distances'][0]]
            logger.warning("Boosting produced no usable chunks, falling back to semantic-only results")
        
        # Step 4: Re-ranking (if enabled); run in thread to avoid blocking event loop
        rerank_count = 0
        if rerank_top_k > 0 and len(documents) > final_top_k:
            logger.info(f"🔄 Re-ranking top {min(rerank_top_k, len(documents))} of {len(documents)} results...")
            
            docs_to_rerank = documents[:min(rerank_top_k, len(documents))]
            metas_to_rerank = metadatas[:min(rerank_top_k, len(metadatas))]
            scores_to_rerank = scores[:min(rerank_top_k, len(scores))]
            
            reranked_docs, reranked_metas, reranked_scores = await asyncio.to_thread(
                self.reranker.rerank_with_metadata,
                query=query,
                documents=docs_to_rerank,
                metadata_list=metas_to_rerank,
                scores_list=scores_to_rerank,
                top_k=final_top_k,
            )
            
            # Combine reranked + remaining
            remaining_docs = documents[min(rerank_top_k, len(documents)):]
            remaining_metas = metadatas[min(rerank_top_k, len(metadatas)):]
            remaining_scores = scores[min(rerank_top_k, len(scores)):]
            
            documents = reranked_docs + remaining_docs
            metadatas = reranked_metas + remaining_metas
            scores = reranked_scores + remaining_scores
            rerank_count = len(docs_to_rerank)
            
            logger.info(
                f"✅ Re-ranked {len(docs_to_rerank)} → top {len(reranked_docs)} (kept {len(remaining_docs)} lower-ranked)",
                extra={'extra_fields': {
                    'event_type': 'rerank',
                    'input_count': len(docs_to_rerank),
                    'output_count': len(reranked_docs),
                    'rerank_top_k': final_top_k
                }}
            )
        
        # Step 5: Filter by explicit filename if provided
        if explicit_filename:
            filtered_docs = []
            filtered_metas = []
            filtered_scores = []
            for doc, meta, score in zip(documents, metadatas, scores):
                if explicit_filename.lower() in meta.get('file_path', '').lower():
                    filtered_docs.append(doc)
                    filtered_metas.append(meta)
                    filtered_scores.append(score)
            if filtered_docs:
                documents = filtered_docs
                metadatas = filtered_metas
                scores = filtered_scores
                logger.info(f"Filtered to {len(documents)} chunks from explicit filename '{explicit_filename}'")
        
        return (documents, metadatas, scores, retrieval_count, rerank_count)
    
    async def _get_document_listing(self, question: str = "") -> QueryResult:
        """
        Get listing of all documents from database.
        Used for document_listing queries. Pass user question so the response can be tailored.
        """
        try:
            from database.database import AsyncSessionLocal
            from database.models import IndexedDocument
            from sqlalchemy import select
            
            async with AsyncSessionLocal() as db_session:
                stmt = select(IndexedDocument).where(
                    IndexedDocument.processing_status.in_(["indexed", "metadata_only"])
                )
                result = await db_session.execute(stmt)
                all_docs = result.scalars().all()
            
            if not all_docs:
                return QueryResult(
                    message="No documents are currently indexed.",
                    sources=[],
                    response_time=0.0,
                    query_type="document_listing",
                    retrieval_count=0,
                    rerank_count=0
                )
            
            # Build context from all documents. Cap per-doc preview so all files fit under
            # provider limit (from adapter); ensures "list all" shows every file.
            sources = []
            context_parts = []
            listing_context_max = self.llm_service.get_max_listing_context_chars()
            per_doc_max = max(80, listing_context_max // len(all_docs)) if all_docs else 500
            for doc in all_docs:
                filename = Path(doc.file_path).name
                if doc.processing_status == "metadata_only":
                    preview = f"[Indexing in progress...] {filename}"
                else:
                    preview = doc.content_preview if doc.content_preview else ""
                    if not preview and doc.chunks_count > 0:
                        preview = f"[File indexed with {doc.chunks_count} chunk(s)]"
                    if len(preview) > per_doc_max:
                        preview = preview[:per_doc_max].rstrip() + "..."
                context_parts.append(f"[Document: {filename}]\n{preview}")
                sources.append({
                    "file_path": doc.file_path,
                    "relevance_score": 1.0,
                    "content_snippet": preview[:300] + "..." if len(preview) > 300 else preview,
                    "chunks_found": doc.chunks_count,
                    "file_type": doc.file_type,
                    "processing_status": doc.processing_status
                })
            
            context = "\n\n---\n\n".join(context_parts)
            
            # Generate response tailored to the user's question (avoids same generic answer for different questions)
            user_question_line = f'The user asked: "{question.strip()}"\n\n' if question and question.strip() else ""
            response_prompt = f"""You are a document assistant. {user_question_line}Here are all indexed documents:

{context}

Tailor your response to what the user asked:
- If they asked what kind or type of files: give a short summary by file format and document category (e.g. "You have PDFs, spreadsheets, Word docs: invoices, permits, reports, ...") and do NOT list every filename.
- If they asked to list, show, or tell about all documents: list each document with filename, brief description, file type, and status.
Be consistent: one style for "kind/type" (summary), another for "list/show all" (full list)."""

            response_text = await self.llm_service.generate_simple(
                response_prompt, prompt_type="document_listing"
            )
            
            return QueryResult(
                message=response_text,
                sources=sources,
                response_time=0.0,  # Will be set by caller
                query_type="document_listing",
                retrieval_count=len(all_docs),
                rerank_count=0
            )
            
        except Exception as e:
            logger.error(f"Document listing failed: {e}")
            return QueryResult(
                message=f"Sorry, I encountered an error while retrieving the document list: {str(e)}",
                sources=[],
                response_time=0.0,
                query_type="document_listing",
                retrieval_count=0,
                rerank_count=0
            )
    
    async def _retrieve_and_build_context(
        self,
        question: str,
        query_type: str,
        query_embedding: List[float],
    ) -> Optional[Dict[str, Any]]:
        """
        Shared retrieval + context-building pipeline for document_search queries.
        Returns dict with context, sources, retrieval_count, rerank_count — or None if no results.
        """
        explicit_filename = self._find_explicit_filename(question)
        selected_files = await self._select_relevant_files(question)
        is_aggregation = is_aggregation_query(question)
        if is_aggregation:
            logger.info("Aggregation-style query detected: using higher recall and per-doc cap")

        documents, metadatas, scores, retrieval_count, rerank_count = await self._retrieve_chunks(
            question, query_type, explicit_filename,
            query_embedding=query_embedding,
            is_aggregation=is_aggregation,
        )
        if not documents:
            return None

        if selected_files:
            prioritized_docs, prioritized_metas, prioritized_scores = [], [], []
            other_docs, other_metas, other_scores = [], [], []
            for doc, meta, score in zip(documents, metadatas, scores):
                fp = meta.get("file_path", "")
                if any(sf in fp for sf in selected_files):
                    prioritized_docs.append(doc)
                    prioritized_metas.append(meta)
                    prioritized_scores.append(score)
                else:
                    other_docs.append(doc)
                    other_metas.append(meta)
                    other_scores.append(score)
            documents = prioritized_docs + other_docs
            metadatas = prioritized_metas + other_metas
            scores = prioritized_scores + other_scores
            logger.info(f"Prioritized {len(prioritized_docs)} chunks from {len(selected_files)} selected files")

        file_chunks: Dict[str, list] = {}
        for doc, metadata, score in zip(documents, metadatas, scores):
            raw_path = metadata.get("file_path", "Unknown")
            fp = os.path.normpath(raw_path) if raw_path else "Unknown"
            file_chunks.setdefault(fp, []).append({
                "text": doc,
                "score": score,
                "chunk_id": metadata.get("chunk_id", 0),
                "metadata": metadata,
            })

        sources: List[Dict] = []
        context_parts: List[str] = []
        files_to_process = file_chunks.items()
        if selected_files:
            files_to_process = [(fp, ch) for fp, ch in file_chunks.items() if any(sf in fp for sf in selected_files)]

        max_per_doc = self.retrieval_config.get_rag_max_per_doc_chars(is_aggregation)
        for fp, chunks in files_to_process:
            chunks.sort(key=lambda x: x["chunk_id"])
            filename = Path(fp).name
            file_text = "\n".join(c["text"] for c in chunks)
            if max_per_doc > 0 and len(file_text) > max_per_doc:
                file_text = file_text[:max_per_doc].rstrip() + "\n[...]"
            context_parts.append(f"[Document: {filename}]\n{file_text}")
            avg_score = sum(c["score"] for c in chunks) / len(chunks)
            snippet = file_text[:300] + "..." if len(file_text) > 300 else file_text
            sources.append({
                "file_path": fp,
                "relevance_score": round(min(1.0, avg_score * 50), 3),
                "content_snippet": snippet,
                "chunks_found": len(chunks),
                "file_type": chunks[0]["metadata"].get("file_type", "unknown"),
            })

        sources.sort(key=lambda x: x["relevance_score"], reverse=True)
        source_limit = self.retrieval_config.get_source_limit(query_type, explicit_filename is not None, is_aggregation)
        sources = sources[:source_limit]

        return {
            "context": "\n\n---\n\n".join(context_parts),
            "sources": sources,
            "retrieval_count": retrieval_count,
            "rerank_count": rerank_count,
        }

    async def query(self, question: str, max_results: int = 15, conversation_history: list = None) -> QueryResult:
        """Query the document index. Routes to greeting/general/listing/search."""
        start_time = asyncio.get_event_loop().time()

        try:
            route_task = asyncio.create_task(self.router.resolve(question, conversation_history))
            embed_task = asyncio.to_thread(self.embedding_service.encode_single_text, question)
            route_result = await route_task
            query_embedding = await embed_task
            query_type = route_result.query_type

            if route_result.route in (Route.GREETING, Route.GENERAL):
                response_text = await self._generate_direct_response(question, query_type)
                return QueryResult(
                    message=response_text, sources=[],
                    response_time=round(asyncio.get_event_loop().time() - start_time, 3),
                    query_type=query_type, retrieval_count=0, rerank_count=0,
                )

            if route_result.route == Route.DOCUMENT_LISTING:
                result = await self._get_document_listing(question=question)
                result.response_time = round(asyncio.get_event_loop().time() - start_time, 3)
                return result

            rag = await self._retrieve_and_build_context(question, query_type, query_embedding)
            if rag is None:
                return QueryResult(
                    message="I don't have information about that in the current documents.",
                    sources=[], response_time=round(asyncio.get_event_loop().time() - start_time, 3),
                    query_type=query_type, retrieval_count=0, rerank_count=0,
                )

            response_text = await self.llm_service.generate_response(
                question, rag["context"], conversation_history=conversation_history or []
            )
            return QueryResult(
                message=response_text, sources=rag["sources"],
                response_time=round(asyncio.get_event_loop().time() - start_time, 3),
                query_type=query_type,
                retrieval_count=rag["retrieval_count"], rerank_count=rag["rerank_count"],
            )

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return QueryResult(
                message=f"Sorry, I encountered an error while processing your query: {str(e)}",
                sources=[], response_time=round(asyncio.get_event_loop().time() - start_time, 3),
                query_type="error",
                retrieval_count=0, rerank_count=0,
            )

    async def query_stream(
        self, question: str, max_results: int = 15, conversation_history: list = None
    ) -> AsyncIterator[Tuple[str, Any]]:
        """Same pipeline as query() but yields SSE events: meta, token, done, error."""
        start_time = asyncio.get_event_loop().time()
        try:
            route_task = asyncio.create_task(self.router.resolve(question, conversation_history))
            embed_task = asyncio.to_thread(self.embedding_service.encode_single_text, question)
            route_result = await route_task
            query_embedding = await embed_task
            query_type = route_result.query_type

            if route_result.route in (Route.GREETING, Route.GENERAL):
                yield ("meta", {"sources": [], "query_type": query_type})
                response_text = await self._generate_direct_response(question, query_type)
                rt = round(asyncio.get_event_loop().time() - start_time, 3)
                yield ("token", response_text)
                yield ("done", {"message": response_text, "response_time": rt, "query_type": query_type, "retrieval_count": 0, "rerank_count": 0})
                return

            if route_result.route == Route.DOCUMENT_LISTING:
                result = await self._get_document_listing(question=question)
                result.response_time = round(asyncio.get_event_loop().time() - start_time, 3)
                yield ("meta", {"sources": result.sources, "query_type": query_type})
                yield ("token", result.message)
                yield ("done", {"message": result.message, "response_time": result.response_time, "query_type": query_type, "retrieval_count": getattr(result, "retrieval_count", 0) or 0, "rerank_count": 0})
                return

            rag = await self._retrieve_and_build_context(question, query_type, query_embedding)
            if rag is None:
                yield ("meta", {"sources": []})
                msg = "I don't have information about that in the current documents."
                yield ("token", msg)
                yield ("done", {"message": msg, "response_time": round(asyncio.get_event_loop().time() - start_time, 3)})
                return

            yield ("meta", {"sources": rag["sources"], "query_type": query_type})
            full_parts: List[str] = []
            async for delta in self.llm_service.generate_response_stream(
                question, rag["context"], conversation_history=conversation_history or []
            ):
                full_parts.append(delta)
                yield ("token", delta)
            rt = round(asyncio.get_event_loop().time() - start_time, 3)
            yield ("done", {"message": "".join(full_parts), "response_time": rt, "query_type": query_type, "retrieval_count": rag["retrieval_count"], "rerank_count": rag["rerank_count"]})
        except Exception as e:
            logger.error(f"Query stream failed: {e}")
            yield ("error", {"detail": str(e)})

    async def get_stats(self) -> Dict:
        """Get comprehensive stats (DB for totals; only a small sample of paths to avoid large payloads)."""
        try:
            collection_count = self.vector_store.get_collection_count()
            db_stats = await self.database_service.get_document_stats()
            total_files = db_stats.get("total_documents", 0) or 0
            # Fetch only a small sample of paths for UI preview; avoid returning hundreds of paths
            indexed_files_sample = await self.database_service.get_indexed_file_paths(limit=20)
            return {
                "total_files": total_files,
                "total_chunks": collection_count,
                "current_directory": self.current_directory,
                "indexed_files_count": total_files,
                "indexed_files": indexed_files_sample,
                "metadata_cache_size": len(self._metadata_cache),
                "avg_chunks_per_file": (collection_count / total_files) if total_files else 0,
                "embedding_model": self.embedding_service.model_name,
                "chunk_size": self.chunker.chunk_size,
                "chunk_overlap": self.chunker.chunk_overlap
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}
    
    async def cleanup(self):
        """Proper cleanup method"""
        try:
            # Cleanup all services
            await self.llm_service.cleanup()
            self.vector_store.cleanup()
            self.embedding_service.cleanup()
            
            self._metadata_cache.clear()
            
            logger.info("DocumentProcessorOrchestrator cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    async def clear_collection(self):
        """Clear all documents from the vector store and reset tracking"""
        try:
            # Clear vector store
            await self.vector_store.clear_collection()
            
            self._metadata_cache.clear()
            self.router.clear_cache()
            
            logger.info("Document collection cleared successfully")
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")
            raise
    
    def is_ready(self) -> bool:
        """Check if the orchestrator is ready (basic services initialized)"""
        try:
            # Check if basic services are available
            return (
                self.text_extractor is not None and
                self.chunker is not None and
                self.file_validator is not None
            )
        except Exception:
            return False
