import asyncio
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

from .models import QueryResult, ProcessingResult, FileMetadata
from .text_extractor import TextExtractor
from .chunker import DocumentChunker
from .embedding_service import EmbeddingService
from .vector_store import VectorStoreService
from .llm_service import LLMService
from .file_validator import FileValidator
from .bm25_service import BM25Service
from .hybrid_search import HybridSearchService
from .reranker_service import ReRankingService
from .filename_trie import FilenameTrie
from .update_queue import UpdateQueue, UpdateTask, UpdatePriority
from .update_executor import UpdateExecutor
from .update_worker import UpdateWorker
from .chunk_differ import ChunkDiffer
from .update_strategy import UpdateStrategySelector
from database import DatabaseService


logger = logging.getLogger(__name__)


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
                 llm_provider: str = "ollama"):
        
        # Initialize all services
        self.text_extractor = TextExtractor()
        self.chunker = DocumentChunker(chunk_size, chunk_overlap)
        self.embedding_service = EmbeddingService(embed_model_name)
        self.vector_store = VectorStoreService(persist_dir)
        # LLM service now supports provider switch (ollama | gemini)
        self.llm_service = LLMService(
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            provider=llm_provider
        )
        self.file_validator = FileValidator(max_file_size_mb)
        self.database_service = DatabaseService()
        
        # Hybrid search services (semantic + keyword)
        self.bm25_service = BM25Service(persist_dir)
        self.hybrid_search = HybridSearchService(k=60)  # RRF constant
        
        # Re-ranking service (cross-encoder for improved relevance)
        self.reranker = ReRankingService(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
        
        # Filename Trie for fast O(m) filename search
        self.filename_trie = FilenameTrie()
        
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
            chunk_differ=self.chunk_differ
        )
        self.update_worker = UpdateWorker(
            update_queue=self.update_queue,
            update_executor=self.update_executor,
            chunk_differ=self.chunk_differ,
            strategy_selector=self.strategy_selector,
            chunker=self.chunker,
            text_extractor=self.text_extractor
        )
        
        # State tracking
        self.file_hashes: Dict[str, str] = {}
        self.file_metadata: Dict[str, FileMetadata] = {}
        self.current_directory: Optional[str] = None
        self.is_initializing: bool = False  # Flag to prevent file monitor events during initial indexing
        self.files_being_processed: set = set()  # Track files currently being indexed to prevent duplicate processing
        
        logger.info("DocumentProcessorOrchestrator initialized with hybrid search (semantic + keyword) and incremental updates")
        
        # Load existing indexed documents into memory
        asyncio.create_task(self._load_existing_metadata())
        
        # Start update worker for incremental updates
        asyncio.create_task(self.update_worker.start())
    
    async def _load_existing_metadata(self):
        """Load existing indexed documents from database into memory"""
        try:
            from database.database import get_db
            from database.models import IndexedDocument
            from sqlalchemy import select
            
            async for db_session in get_db():
                # Load both indexed and metadata_only documents
                stmt = select(IndexedDocument).where(
                    IndexedDocument.processing_status.in_(["indexed", "metadata_only"])
                )
                result = await db_session.execute(stmt)
                docs = result.scalars().all()
                
                for doc in docs:
                    # Reconstruct file metadata
                    self.file_metadata[doc.file_path] = {
                        "file_type": doc.file_type,
                        "size_bytes": doc.file_size,
                        "modified_at": doc.last_modified,
                        "chunks": doc.chunks_count,
                        "processing_status": doc.processing_status
                    }
                    self.file_hashes[doc.file_path] = doc.file_hash
                
                    # Rebuild Filename Trie from existing documents
                    filename = Path(doc.file_path).name
                    self.filename_trie.add(filename, doc.file_path)
                
                indexed_count = sum(1 for doc in docs if doc.processing_status == "indexed")
                metadata_only_count = sum(1 for doc in docs if doc.processing_status == "metadata_only")
                logger.info(f"📚 Loaded {len(docs)} documents into memory "
                          f"({indexed_count} indexed, {metadata_only_count} metadata-only)")
                logger.info(f"📊 Filename Trie rebuilt with {len(docs)} files")
                break
                
        except Exception as e:
            logger.warning(f"Could not load existing metadata: {e}")
    
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
        self.file_hashes.clear()
        self.file_metadata.clear()
        self.files_being_processed.clear()  # Clear processing set to prevent stale entries
        logger.info("Vector store cleared")
        
        # Clear BM25 index
        self.bm25_service.clear()
        logger.info("BM25 index cleared")
        
        # Clear Filename Trie
        self.filename_trie.clear()
        logger.info("Filename Trie cleared")
        
        # Clear database records
        try:
            from database.database import get_db
            from database.models import IndexedDocument
            from sqlalchemy import delete
            
            async for session in get_db():
                stmt = delete(IndexedDocument)
                await session.execute(stmt)
                await session.commit()
                logger.info("Database document index records cleared")
                break
        except Exception as e:
            logger.warning(f"Failed to clear database records: {e}")
    
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
            
            if self.current_directory == directory_path and len(self.file_hashes) > 0:
                logger.info(f"Directory {directory_path} already initialized with {len(self.file_hashes)} files, skipping re-initialization")
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
            asyncio.create_task(
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
        """
        logger.info(f"🔄 Background content indexing started for {len(file_paths)} files")
        
        batch_size = 10
        processed = 0
        failed = 0
        
        try:
            for i in range(0, len(file_paths), batch_size):
                batch = file_paths[i:i + batch_size]
                
                # Process batch concurrently
                tasks = [self._process_single_file(file_path) for file_path in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Count results
                for result in results:
                    if isinstance(result, Exception):
                        failed += 1
                        logger.error(f"Background indexing failed: {result}")
                    else:
                        processed += 1
                
                # Log progress every batch
                if (i + batch_size) % 50 == 0 or i + batch_size >= len(file_paths):
                    logger.info(f"📊 Background indexing progress: {processed + failed}/{len(file_paths)} files "
                              f"({processed} indexed, {failed} failed)")
                
                # Small delay between batches to avoid overwhelming the system
                if i + batch_size < len(file_paths):
                    await asyncio.sleep(0.1)
            
            logger.info(f"✅ Background content indexing complete: {processed} indexed, {failed} failed")
                
        except Exception as e:
            logger.error(f"Background content indexing error: {e}")
    
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
            
            # Get last queried time (if available)
            last_queried = datetime.utcnow()  # Default to now
            if file_path in self.file_metadata:
                metadata = self.file_metadata[file_path]
                if isinstance(metadata, dict):
                    last_queried = metadata.get("modified_at", datetime.utcnow())
                else:
                    last_queried = metadata.modified_at if hasattr(metadata, 'modified_at') else datetime.utcnow()
            
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
            # Check if file has changed
            current_hash = self.file_validator.calculate_file_hash(file_path)
            stored_hash = self.file_hashes.get(file_path)
            
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
            stored_hash = self.file_hashes.get(file_path)
            if not force_reindex and stored_hash == current_hash:
                logger.debug(f"File {file_path} unchanged, skipping re-index")
                # Remove from processing set before returning
                self.files_being_processed.discard(file_path)
                return
            
            # Check if document exists in database and get current status
            from database.database import get_db
            from database.models import IndexedDocument
            from sqlalchemy import select
            
            async for db_session in get_db():
                stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
                result = await db_session.execute(stmt)
                existing_doc = result.scalar_one_or_none()
                
                # If document exists and is already fully indexed with same hash, skip
                if existing_doc and existing_doc.processing_status == "indexed" and existing_doc.file_hash == current_hash:
                    if not force_reindex:
                        logger.debug(f"File {file_path} already fully indexed, skipping")
                        # Update in-memory tracking
                        self.file_hashes[file_path] = current_hash
                        self.file_metadata[file_path] = file_metadata
                        # Remove from processing set before returning
                        self.files_being_processed.discard(file_path)
                        return
                
                # If document exists with metadata_only status, it needs to be upgraded to indexed
                # Continue processing to upgrade from metadata_only to indexed
                # (No need to check files_being_processed here since we already added it above)
                
                break
            
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
            embeddings = self.embedding_service.encode_texts([chunk.text for chunk in chunks])
            await self.vector_store.batch_insert_chunks(chunks, embeddings)
            
            # Add to BM25 keyword index
            bm25_documents = [
                {
                    'id': f"{chunk.file_path}:{chunk.chunk_id}",  # Create unique ID
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
            
            # Store complete metadata in database (updates from metadata_only to indexed)
            await self.database_service.store_document_metadata(
                file_path=file_path,
                file_hash=current_hash,
                file_type=file_metadata["file_type"],
                file_size=file_metadata["size_bytes"],
                last_modified=file_metadata["modified_at"],
                content_preview=text[:500],
                chunks_count=len(chunks),
                processing_status="indexed"  # Mark as fully indexed
            )
            
            # Update tracking
            self.file_hashes[file_path] = current_hash
            self.file_metadata[file_path] = file_metadata
            
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
            
            # Clean up tracking
            self.file_hashes.pop(file_path, None)
            self.file_metadata.pop(file_path, None)
            
            logger.info(f"Removed document: {file_path}")
            
        except Exception as e:
            logger.error(f"Error removing document {file_path}: {e}")
    
    def _is_simple_filename_query(self, question: str) -> bool:
        """
        Detect if query is a simple filename-based query that can use Trie.
        
        Simple queries:
        - Contains filename patterns: "TCO", "sales", "invoice"
        - Contains file type: "PDF files", "DOCX files"
        - Contains prefix indicators: "files starting with", "files containing"
        - Simple patterns: "show me X files"
        
        Complex queries (need LLM):
        - Content-based: "files about sales", "documents mentioning revenue"
        - Negation: "files NOT receipts"
        - Semantic: "documents from October"
        """
        question_lower = question.lower()
        
        # Simple filename query indicators
        filename_indicators = [
            'files starting with',
            'files containing',
            'files with',
            'show me',
            'list',
            'how many',
            'what files',
            'which files',
            'all files',
            'files ending with',
            'files that start',
        ]
        
        # File type queries
        file_type_patterns = [
            r'\bpdf\s+files?\b',
            r'\bdocx?\s+files?\b',
            r'\bexcel\s+files?\b',
            r'\btext\s+files?\b',
            r'\b\.pdf\b',
            r'\b\.docx?\b',
            r'\b\.txt\b',
            r'\b\.xlsx?\b',
        ]
        
        # Check for simple indicators
        has_filename_indicator = any(indicator in question_lower for indicator in filename_indicators)
        has_file_type = any(re.search(pattern, question_lower) for pattern in file_type_patterns)
        
        # Check for complex query indicators (need LLM)
        complex_indicators = [
            'about',
            'mentioning',
            'containing',
            'related to',
            'not',
            'except',
            'excluding',
            'without',
            'from',
            'to',
            'between',
            'after',
            'before',
        ]
        
        # If it has complex indicators, it's likely content-based
        has_complex_indicator = any(indicator in question_lower for indicator in complex_indicators)
        
        # Simple query if it has filename/file type indicators but NOT complex content indicators
        is_simple = (has_filename_indicator or has_file_type) and not has_complex_indicator
        
        logger.debug(f"Query '{question}' → simple_filename_query: {is_simple}")
        return is_simple
    
    def _extract_filename_patterns(self, question: str) -> List[str]:
        """
        Extract filename patterns from query for Trie search.
        
        Examples:
        - "TCO files" → ["tco"]
        - "PDF files" → ["pdf"] (file type)
        - "files starting with SAL" → ["sal"]
        - "show me sales and invoice files" → ["sales", "invoice"]
        """
        patterns = []
        question_lower = question.lower()
        
        # Extract file types
        file_types = ['pdf', 'docx', 'doc', 'txt', 'xlsx', 'xls']
        for file_type in file_types:
            if file_type in question_lower:
                patterns.append(file_type)
        
        # Extract "starting with X" patterns
        match = re.search(r'(?:starting with|containing|with)\s+([a-z0-9]+)', question_lower)
        if match:
            patterns.append(match.group(1))
        
        # Extract potential filename keywords (2+ character words that might be filenames)
        # Look for capitalized words or common filename patterns
        words = re.findall(r'\b[A-Z][A-Z0-9]{1,}\b', question)  # TCO, SALES, etc.
        patterns.extend([w.lower() for w in words])
        
        # Extract quoted strings (likely filenames)
        quoted = re.findall(r'"([^"]+)"', question)
        patterns.extend([q.lower() for q in quoted])
        
        # Also extract common filename patterns from the query
        # Look for words that appear to be filenames (not common words)
        common_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 
                       'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'can',
                       'show', 'me', 'all', 'files', 'file', 'document', 'documents', 'list', 'what',
                       'which', 'how', 'many', 'about', 'with', 'from', 'to', 'in', 'on', 'at', 'for'}
        
        # Extract meaningful words (not common words, 2+ chars)
        query_words = re.findall(r'\b[a-z]{2,}\b', question_lower)
        meaningful_words = [w for w in query_words if w not in common_words and len(w) >= 2]
        patterns.extend(meaningful_words[:3])  # Limit to top 3 to avoid noise
        
        # Remove duplicates and empty strings
        patterns = list(set([p.lower().strip() for p in patterns if len(p.strip()) >= 2]))
        
        logger.debug(f"Extracted filename patterns from '{question}': {patterns}")
        return patterns
    
    async def _select_relevant_files(self, question: str) -> Optional[List[str]]:
        """
        Intelligently select relevant files using Trie (fast) or LLM (semantic).
        Returns None if all files should be considered (general query).
        Returns list of file paths if specific files are relevant.
        """
        try:
            # Get all indexed files with their metadata
            if not self.file_metadata:
                logger.info("No files indexed, skipping file selection")
                return None
            
            # Check if this is a simple filename query (use Trie)
            if self._is_simple_filename_query(question):
                logger.info(f"🔍 Detected simple filename query, using Trie search")
                
                # Extract filename patterns from query
                patterns = self._extract_filename_patterns(question)
                
                if patterns:
                    # Search Trie for each pattern
                    matching_files = set()
                    for pattern in patterns:
                        trie_results = self.filename_trie.search(pattern)
                        matching_files.update(trie_results)
                    
                    # Also check for file type queries
                    question_lower = question.lower()
                    file_type_map = {
                        'pdf': 'pdf',
                        'docx': 'docx',
                        'doc': 'doc',
                        'txt': 'txt',
                        'text': 'txt',
                        'excel': 'xlsx',
                        'xlsx': 'xlsx',
                    }
                    
                    for query_word, file_type in file_type_map.items():
                        if query_word in question_lower:
                            type_results = self.filename_trie.search_by_file_type('', file_type)
                            matching_files.update(type_results)
                    
                    if matching_files:
                        file_list = list(matching_files)
                        logger.info(f"✅ Trie found {len(file_list)} matching files (instant, $0)")
                        return file_list
                    else:
                        logger.info(f"⚠️ Trie found no matches, falling back to LLM")
                        # Fall through to LLM
                else:
                    logger.info(f"⚠️ No filename patterns extracted, using LLM")
                    # Fall through to LLM
            
            # Complex query or Trie found nothing - use LLM
            logger.info(f"🤖 Using LLM for file selection (complex query or no Trie matches)")
            return await self._llm_select_files(question)
            
        except Exception as e:
            logger.error(f"File selection failed: {e}, falling back to all files")
            return None
    
    async def _llm_select_files(self, question: str) -> Optional[List[str]]:
        """
        Use LLM to intelligently select which files are relevant to the query.
        This is the original LLM-based file selection method.
        """
        try:
            
            # Build file list for LLM
            file_list = []
            file_paths_list = list(self.file_metadata.keys())
            for idx, file_path in enumerate(file_paths_list, 1):
                filename = Path(file_path).name
                metadata = self.file_metadata[file_path]
                file_type = metadata.get("file_type", "unknown")
                file_list.append(f"{idx}. {filename} (type: {file_type})")
            
            file_list_str = "\n".join(file_list)
            
            # Create selection prompt
            selection_prompt = f"""You are a file selection AI. Your ONLY job is to pick which files are needed to answer a question.

AVAILABLE FILES:
{file_list_str}

USER QUESTION: "{question}"

IMPORTANT: You can ONLY see filenames, NOT document content!

INSTRUCTIONS:
• If the question is about DOCUMENT CONTENT (not filenames), respond: ALL_FILES
• If the question is about SPECIFIC FILENAMES or filename patterns, select those files
• If uncertain, respond: ALL_FILES (better to include too many than miss relevant files)

CONTENT-BASED QUERIES (respond ALL_FILES):
• "List delivery receipts" → Content-based, you can't see content → ALL_FILES
• "Documents about sales" → Content-based → ALL_FILES  
• "Find acknowledgement receipts" → Content-based → ALL_FILES
• "Show me invoices" → Content-based → ALL_FILES

FILENAME-BASED QUERIES (select specific files):
• "What's in REQUEST LETTER?" → Filename match → Return: 5
• "How many TCO files?" → Filename pattern → Return: 1,2,7,9
• "Show me all PDF files" → File type → Return: 2,3,4,5
• "Files starting with PES" → Filename pattern → Return: 4,5

CRITICAL RULES:
1. If query is about document CONTENT → return ALL_FILES
2. If query is about FILENAMES or patterns → select specific files
3. When in doubt → return ALL_FILES
4. Only return numbers or "ALL_FILES"
5. NO explanations, NO other text

YOUR RESPONSE (ONLY numbers or "ALL_FILES"):"""

            # Get LLM selection (use simple method without templating)
            response = await self.llm_service.generate_simple(selection_prompt)
            
            response = response.strip()
            logger.info(f"🤖 LLM file selection response: {response}")
            
            # Handle error responses from LLM
            if "couldn't generate" in response.lower() or "error" in response.lower():
                logger.warning(f"LLM selection failed, falling back to ALL files")
                return None
            
            # Parse response
            if "ALL_FILES" in response.upper() or response.upper() == "ALL":
                logger.info("📋 LLM decided: ALL files are relevant (general query)")
                return None
            
            # Parse file numbers - be more flexible with parsing
            try:
                # Remove any text, keep only numbers and commas
                # Handle responses like "1,3,5,7" or "1, 3, 5, 7" or even "Files: 1,3,5"
                cleaned = ''.join(c for c in response if c.isdigit() or c == ',')
                if not cleaned:
                    logger.warning(f"No numbers found in LLM response: '{response}'")
                    return None
                
                file_numbers = [int(num.strip()) for num in cleaned.split(",") if num.strip()]
                file_paths_list = list(self.file_metadata.keys())
                
                selected_files = []
                for num in file_numbers:
                    if 1 <= num <= len(file_paths_list):
                        selected_files.append(file_paths_list[num - 1])
                    else:
                        logger.warning(f"File number {num} out of range (1-{len(file_paths_list)})")
                
                if selected_files:
                    selected_names = [Path(f).name for f in selected_files]
                    logger.info(f"🎯 LLM selected {len(selected_files)} specific files: {selected_names}")
                    return selected_files
                else:
                    logger.warning(f"LLM returned invalid file numbers: {response}")
                    return None
                    
            except ValueError as e:
                logger.warning(f"Failed to parse LLM response '{response}': {e}")
                return None
                
        except Exception as e:
            logger.error(f"File selection failed: {e}, falling back to all files")
            return None
    
    async def _classify_query(self, question: str, conversation_history: list = None) -> str:
        """
        Classify the query to determine if document retrieval is needed.
        Returns: 'greeting', 'general', or 'document'
        """
        try:
            # Build conversation context if available
            conversation_context = ""
            if conversation_history:
                conversation_context = "\n\nRecent conversation context:\n"
                for msg in conversation_history[-2:]:  # Last 2 messages for classification
                    role = "User" if msg["role"] == "user" else "Assistant"
                    conversation_context += f"{role}: {msg['content'][:150]}...\n"
            
            classification_prompt = f"""You are a query classification AI. Classify the user's query into ONE of these categories:
{conversation_context}
USER QUERY: "{question}"

CATEGORIES:
1. greeting - Simple greetings, pleasantries, or introductions
   Examples: "hello", "hi", "how are you?", "good morning", "thanks", "goodbye"
   
2. general - General questions NOT about documents, or questions about the AI itself (ONLY if not a follow-up)
   Examples: "what can you do?", "how does this work?", "who made you?", "what's the weather?"
   
3. document - Questions that need document retrieval to answer
   Examples: "what's in the sales report?", "how many TCO documents?", "summarize the meeting notes"

🚨 CRITICAL: FOLLOW-UP QUESTION DETECTION 🚨
If the query contains ANY of these, it's ALWAYS "document":
• Pronouns: "that", "it", "this", "those", "them", "which", "what about"
• File references: "that file", "the file", "the document", "that one", "this one"
• Questions about previous context: "who", "what", "where", "when", "why", "how" + pronoun

EXAMPLES OF FOLLOW-UPS (all are "document"):
• "Who is the driver on that?" → "document" (pronoun "that" refers to previous file)
• "What about this one?" → "document" (pronoun "this")
• "Tell me more about it" → "document" (pronoun "it")
• "Which is the latest?" → "document" (pronoun "which" implies previous list)
• "How many are there?" → "document" (pronoun "there" implies previous context)

SAFE DEFAULT RULE:
⚠️ If you're even 1% unsure whether it's a follow-up → return "document" (it's safer to search than miss context)

INSTRUCTIONS:
- Respond with ONLY ONE WORD: "greeting", "general", or "document"
- Check conversation context FIRST - if query relates to any previous message, return "document"
- NO explanations, NO other text, NO punctuation

YOUR CLASSIFICATION (ONE WORD):"""

            response = await self.llm_service.generate_simple(classification_prompt)
            classification = response.strip().lower()
            
            # Additional heuristic: check for pronouns that indicate follow-up questions
            follow_up_indicators = ['that', 'it', 'this', 'those', 'them', 'the file', 'the document', 
                                   'that file', 'that document', 'which one', 'what about']
            query_lower = question.lower()
            has_follow_up_indicator = any(indicator in query_lower for indicator in follow_up_indicators)
            
            # If query has follow-up indicators, force it to be 'document'
            if has_follow_up_indicator and classification in ['general', 'greeting']:
                logger.info(f"🔍 Query contains follow-up indicators, overriding '{classification}' → DOCUMENT")
                return 'document'
            
            # Validate response
            if classification in ['greeting', 'general', 'document']:
                logger.info(f"🔍 Query classified as: {classification.upper()}")
                return classification
            else:
                # If LLM returns something unexpected, default to 'document' (safe fallback)
                logger.warning(f"Unexpected classification '{response}', defaulting to 'document'")
                return 'document'
                
        except Exception as e:
            logger.error(f"Query classification failed: {e}, defaulting to 'document'")
            return 'document'
    
    async def _rewrite_query(self, question: str, conversation_history: list = None) -> str:
        """
        Rewrite ambiguous queries using conversation context for better retrieval.
        
        Examples:
        - "Who drove that?" → "Who is the driver in [previous file mentioned]?"
        - "What about this one?" → "What are the contents of [file name from previous message]?"
        - "Tell me more" → "Tell me more about [topic from previous message]"
        
        Args:
            question: Original query (may contain pronouns, references)
            conversation_history: Previous conversation messages
            
        Returns:
            Rewritten query with explicit context, or original if no rewriting needed
        """
        try:
            conversation_history = conversation_history or []
            
            # Check if query needs rewriting (has pronouns or ambiguous references)
            ambiguous_indicators = [
                'that', 'it', 'this', 'those', 'them', 'which', 'what about',
                'the file', 'the document', 'that file', 'that document',
                'this one', 'that one', 'tell me more', 'what about'
            ]
            
            query_lower = question.lower()
            needs_rewriting = any(indicator in query_lower for indicator in ambiguous_indicators)
            
            # If no conversation history or query is already explicit, skip rewriting
            if not conversation_history or not needs_rewriting:
                logger.debug(f"Query does not need rewriting: '{question}'")
                return question
            
            # Build conversation context
            conversation_context = "\n\nPrevious conversation:\n"
            for msg in conversation_history[-4:]:  # Last 4 messages for context
                role = "User" if msg["role"] == "user" else "Assistant"
                content = msg["content"][:200]  # Limit length
                conversation_context += f"{role}: {content}\n"
            
            rewriting_prompt = f"""You are a query rewriting AI. Your job is to rewrite ambiguous user queries by replacing pronouns and references with explicit information from the conversation context.

CONVERSATION CONTEXT:
{conversation_context}

USER QUERY: "{question}"

INSTRUCTIONS:
- Replace pronouns ("that", "it", "this", etc.) with explicit references from the conversation
- Replace file references ("that file", "the document") with actual filenames mentioned
- If the query asks "who" or "what" about something previously mentioned, make it explicit
- Keep the rewritten query concise and natural
- If the query is already explicit or you can't determine the reference, return the original query unchanged

EXAMPLES:
- "Who drove that?" → "Who is the driver in TCO005 10.14 ABI.pdf?"
- "What about this one?" → "What are the contents of PES starter_005.pdf?"
- "Tell me more about it" → "Tell me more about the delivery receipt TCO005"
- "Who is the driver on that file?" → "Who is the driver in TCO005 10.14 ABI.pdf?"

CRITICAL RULES:
1. Only rewrite if pronouns/references can be resolved from context
2. If unsure, return the original query (don't guess)
3. Preserve the user's intent and question structure
4. Keep it concise (max 20 words)

REWRITTEN QUERY (or original if no changes needed):"""

            rewritten = await self.llm_service.generate_simple(rewriting_prompt)
            rewritten = rewritten.strip().strip('"').strip("'")  # Clean up quotes
            
            # Validate: don't use if it's too different or seems like an error response
            if rewritten and len(rewritten) > 5 and "couldn't" not in rewritten.lower():
                if rewritten.lower() != question.lower():
                    logger.info(f"🔄 Query rewritten: '{question}' → '{rewritten}'")
                    return rewritten
                else:
                    logger.debug(f"LLM decided query doesn't need rewriting: '{question}'")
                    return question
            else:
                logger.warning(f"Query rewriting returned invalid result, using original: '{rewritten}'")
                return question
                
        except Exception as e:
            logger.warning(f"Query rewriting failed: {e}, using original query")
            return question
    
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
            response = await self.llm_service.generate_simple(prompt)
            
            return response
            
        except Exception as e:
            logger.error(f"Direct response generation failed: {e}")
            return "Hello! I'm your document assistant. I can help you search and analyze your indexed documents. What would you like to know?"
    
    async def query(self, question: str, max_results: int = 15, conversation_history: list = None) -> QueryResult:
        """Query the document index with agentic LLM-based classification and file selection"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Step 0: Classify query to determine if document retrieval is needed
            query_type = await self._classify_query(question, conversation_history)
            
            # Handle non-document queries directly (fast path)
            if query_type in ['greeting', 'general']:
                response_text = await self._generate_direct_response(question, query_type)
                response_time = asyncio.get_event_loop().time() - start_time
                
                logger.info(f"⚡ Fast response (no retrieval): {response_time:.2f}s")
                
                return QueryResult(
                    message=response_text,
                    sources=[],  # No document sources for greetings/general
                    response_time=round(response_time, 3),
                    query_type=query_type,
                    retrieval_count=0,
                    rerank_count=0
                )
            
            # Document query - proceed with RAG pipeline
            logger.info(f"📚 Document query detected, starting RAG pipeline...")
            
            # Track metrics for structured logging
            retrieval_count = 0
            rerank_count = 0
            
            # Step 0.5: Rewrite ambiguous queries using conversation context
            rewritten_question = await self._rewrite_query(question, conversation_history)
            # Use rewritten query for retrieval, but keep original for LLM response
            retrieval_query = rewritten_question if rewritten_question != question else question
            
            # Step 1: Detect listing queries (need to see ALL documents)
            listing_query_patterns = [
                'list', 'all documents', 'all files', 'what documents', 'what files',
                'show me documents', 'show me files', 'how many documents', 'how many files',
                'document list', 'file list', 'enumerate', 'inventory'
            ]
            is_listing_query = any(pattern in question.lower() for pattern in listing_query_patterns)
            
            # Step 2: Intelligently select relevant files using Trie (fast) or LLM (semantic)
            selected_files = await self._select_relevant_files(retrieval_query)
            
            # Step 3: Special handling for listing queries (use database, not semantic search)
            if is_listing_query:
                logger.info(f"📋 Listing query detected: fetching all indexed documents from database...")
                try:
                    from database.database import get_db
                    from database.models import IndexedDocument
                    from sqlalchemy import select
                    
                    # Get all documents from database (both indexed and metadata-only for listing)
                    all_docs = []
                    async for db_session in get_db():
                        stmt = select(IndexedDocument).where(
                            IndexedDocument.processing_status.in_(["indexed", "metadata_only"])
                        )
                        result = await db_session.execute(stmt)
                        all_docs = result.scalars().all()
                        break
                    
                    if not all_docs:
                        return QueryResult(
                            message="No documents are currently indexed.",
                            sources=[],
                            response_time=asyncio.get_event_loop().time() - start_time,
                            query_type=query_type,
                            retrieval_count=0,
                            rerank_count=0
                        )
                    
                    # Build sources from database records
                    sources = []
                    context_parts = []
                    for doc in all_docs:
                        filename = Path(doc.file_path).name
                        
                        # Handle metadata-only documents (still being indexed)
                        if doc.processing_status == "metadata_only":
                            preview = f"[Indexing in progress...] {filename}"
                            content_snippet = "Content is being indexed in the background."
                        else:
                            preview = doc.content_preview if doc.content_preview else ""
                            content_snippet = preview[:300] + "..." if len(preview) > 300 else preview
                            context_parts.append(f"[Document: {filename}]\n{preview}")
                        
                        sources.append({
                            "file_path": doc.file_path,
                            "relevance_score": 1.0,  # All equally relevant for listing
                            "content_snippet": content_snippet,
                            "chunks_found": doc.chunks_count,
                            "file_type": doc.file_type,
                            "processing_status": doc.processing_status  # Include status
                        })
                    
                    logger.info(f"📋 Found {len(all_docs)} indexed documents in database")
                    
                    # Generate response using all documents
                    context = "\n\n---\n\n".join(context_parts)
                    response_text = await self.llm_service.generate_response(
                        question,
                        context,
                        conversation_history=conversation_history or []
                    )
                    
                    return QueryResult(
                        message=response_text,
                        sources=sources,
                        response_time=asyncio.get_event_loop().time() - start_time,
                        query_type=query_type,
                        retrieval_count=len(all_docs),  # Number of documents from DB
                        rerank_count=0  # Listing queries don't use re-ranking
                    )
                    
                except Exception as e:
                    logger.warning(f"Failed to fetch from database for listing query: {e}, falling back to hybrid search")
                    # Fall through to hybrid search
            
            # Step 4: Adjust retrieval parameters based on query type
            if is_listing_query:
                # Listing query - retrieve MANY chunks to cover all documents
                adjusted_max_results = min(max_results * 8, 120)
                logger.info(f"📋 Listing query detected: increasing retrieval to {adjusted_max_results} chunks")
            elif selected_files is not None:
                # Specific files selected - retrieve more chunks to ensure good coverage
                adjusted_max_results = min(max_results * 2, 30)
            else:
                # General query - retrieve chunks from all files
                adjusted_max_results = min(max_results * 4, 60)
            
            # Step 5: Hybrid Search (Semantic with BM25 boosting)
            logger.info(f"🔍 Performing hybrid search (semantic with BM25 boost)...")
            
            # 5a. Semantic search (ChromaDB) - use rewritten query for better retrieval
            query_embedding = self.embedding_service.encode_single_text(retrieval_query)
            semantic_results = await self.vector_store.search_similar(query_embedding, adjusted_max_results)
            
            if not semantic_results['documents'] or not semantic_results['documents'][0]:
                return QueryResult(
                    message="I don't have information about that in the current documents.",
                    sources=[],
                    response_time=asyncio.get_event_loop().time() - start_time,
                    query_type=query_type,
                    retrieval_count=0,
                    rerank_count=0
                )
            
            # 5b. Keyword search (BM25) - used only to BOOST semantic results (use rewritten query)
            bm25_results_raw = self.bm25_service.search(retrieval_query, top_k=adjusted_max_results)
            bm25_hits = set()
            for doc_id, score, meta in (bm25_results_raw or []):
                fp = meta.get('file_path', '')
                cid = meta.get('chunk_id')
                if fp is not None and cid is not None:
                    bm25_hits.add((fp, cid))
            
            semantic_count = len(semantic_results['documents'][0]) if semantic_results['documents'] else 0
            keyword_count = len(bm25_results_raw) if bm25_results_raw else 0
            
            logger.info(
                f"🔍 Hybrid search: {semantic_count} semantic, {len(bm25_hits)} BM25 boosts",
                extra={'extra_fields': {
                    'event_type': 'retrieval',
                    'semantic_results': semantic_count,
                    'keyword_results': keyword_count,
                    'bm25_boosts': len(bm25_hits)
                }}
            )
            
            # Build boosted semantic results; do NOT include BM25-only items
            documents = []
            metadatas = []
            boosted_scores = []
            
            for doc, meta, dist in zip(
                semantic_results['documents'][0],
                semantic_results['metadatas'][0],
                semantic_results['distances'][0]
            ):
                base_score = max(0.0, 1.0 - float(dist))  # Convert distance to similarity
                fp = meta.get('file_path', '')
                cid = meta.get('chunk_id')
                boost = 0.0
                if (fp, cid) in bm25_hits:
                    boost = 0.1  # modest boost for exact keyword match
                final_score = min(1.0, base_score + boost)
                
                # Append only if doc text is non-empty
                if doc and doc.strip():
                    documents.append(doc)
                    metadatas.append(meta)
                    boosted_scores.append(final_score)
                else:
                    logger.warning(f"Skipping empty semantic chunk for {fp}#{cid}")
            
            # Guard: if we lost everything (shouldn't happen), fall back to unboosted semantic
            if not documents:
                documents = semantic_results['documents'][0]
                metadatas = semantic_results['metadatas'][0]
                boosted_scores = [max(0.0, 1.0 - float(d)) for d in semantic_results['distances'][0]]
                logger.warning("Boosting produced no usable chunks, falling back to semantic-only results")
            
            # Track retrieval count
            retrieval_count = len(documents)
            
            # Wrap in results structure
            results = {
                'documents': [documents],
                'metadatas': [metadatas],
                'distances': [boosted_scores]  # store similarity-like scores
            }
            
            # Step 6: Process results and prioritize selected files
            documents = results['documents'][0]
            metadatas = results['metadatas'][0] 
            distances = results['distances'][0]
            
            # If LLM selected specific files, prioritize their chunks
            if selected_files:
                prioritized_docs = []
                prioritized_metas = []
                prioritized_dists = []
                other_docs = []
                other_metas = []
                other_dists = []
                
                for doc, meta, dist in zip(documents, metadatas, distances):
                    file_path = meta.get("file_path", "")
                    if any(sf in file_path for sf in selected_files):
                        prioritized_docs.append(doc)
                        prioritized_metas.append(meta)
                        prioritized_dists.append(dist)
                    else:
                        other_docs.append(doc)
                        other_metas.append(meta)
                        other_dists.append(dist)
                
                # Reconstruct with prioritized first
                documents = prioritized_docs + other_docs
                metadatas = prioritized_metas + other_metas
                distances = prioritized_dists + other_dists
                
                logger.info(f"✅ Prioritized {len(prioritized_docs)} chunks from {len(selected_files)} selected files")
            
            # Step 6.5: Re-rank top results for improved relevance (skip for listing queries)
            rerank_top_k = 15  # Re-rank top 15, then take top 5
            final_top_k = 5    # Final top K after re-ranking
            
            if not is_listing_query and len(documents) > final_top_k:
                logger.info(f"🔄 Re-ranking top {min(rerank_top_k, len(documents))} of {len(documents)} results...")
                
                # Re-rank top chunks
                documents_to_rerank = documents[:min(rerank_top_k, len(documents))]
                metadatas_to_rerank = metadatas[:min(rerank_top_k, len(metadatas))]
                scores_to_rerank = distances[:min(rerank_top_k, len(distances))]
                
                # Perform re-ranking (use rewritten query for better relevance)
                reranked_docs, reranked_metas, reranked_scores = self.reranker.rerank_with_metadata(
                    query=retrieval_query,
                    documents=documents_to_rerank,
                    metadata_list=metadatas_to_rerank,
                    scores_list=scores_to_rerank,
                    top_k=final_top_k
                )
                
                # Combine reranked results with remaining lower-ranked results
                remaining_docs = documents[min(rerank_top_k, len(documents)):]
                remaining_metas = metadatas[min(rerank_top_k, len(metadatas)):]
                remaining_scores = distances[min(rerank_top_k, len(distances)):]
                
                documents = reranked_docs + remaining_docs
                metadatas = reranked_metas + remaining_metas
                distances = reranked_scores + remaining_scores
                
                # Track re-ranking count
                rerank_count = len(documents_to_rerank)
                
                logger.info(
                    f"✅ Re-ranked {len(documents_to_rerank)} → top {len(reranked_docs)} (kept {len(remaining_docs)} lower-ranked)",
                    extra={'extra_fields': {
                        'event_type': 'rerank',
                        'input_count': len(documents_to_rerank),
                        'output_count': len(reranked_docs),
                        'rerank_top_k': final_top_k
                    }}
                )
            elif not is_listing_query:
                logger.debug(f"Skipping re-ranking: only {len(documents)} results (need > {final_top_k})")
            
            # Step 7: Group chunks by file for better context
            file_chunks = {}
            for doc, metadata, score in zip(documents, metadatas, distances):  # 'distances' is actually scores now
                file_path = metadata.get("file_path", "Unknown")
                if file_path not in file_chunks:
                    file_chunks[file_path] = []
                file_chunks[file_path].append({
                    "text": doc,
                    "score": score,  # RRF score (higher = better)
                    "chunk_id": metadata.get("chunk_id", 0),
                    "metadata": metadata
                })
            
            # Step 7: Create sources and context from selected files
            sources = []
            context_parts = []
            
            # Filter files based on file selection (Trie or LLM)
            files_to_process = file_chunks.items()
            if selected_files:
                # Only include selected files - NO additional context files for specific queries
                selected_file_chunks = {fp: chunks for fp, chunks in file_chunks.items() if any(sf in fp for sf in selected_files)}
                
                files_to_process = list(selected_file_chunks.items())
                logger.info(f"🎯 Focusing exclusively on {len(selected_file_chunks)} selected file(s)")
            
            for file_path, chunks in files_to_process:
                # Sort chunks by chunk_id for proper order
                chunks.sort(key=lambda x: x["chunk_id"])
                
                # Get just the filename for better readability
                filename = Path(file_path).name
                
                # Combine chunks for this file WITH filename header
                file_text = "\n".join([chunk["text"] for chunk in chunks])
                # Format: [Filename: xyz.pdf]\nContent...
                context_with_filename = f"[Document: {filename}]\n{file_text}"
                context_parts.append(context_with_filename)
                
                # Calculate average relevance from RRF scores
                avg_score = sum(chunk["score"] for chunk in chunks) / len(chunks)
                # Normalize RRF score to percentage (RRF scores are typically 0.01-0.05)
                # Multiply by 100 to get percentage, cap at 100%
                relevance_score = min(1.0, avg_score * 50)  # Scale RRF scores to ~0-1 range
                
                sources.append({
                    "file_path": file_path,
                    "relevance_score": round(relevance_score, 3),
                    "content_snippet": file_text[:300] + "..." if len(file_text) > 300 else file_text,
                    "chunks_found": len(chunks),
                    "file_type": chunks[0]["metadata"].get("file_type", "unknown")
                })
            
            # Sort sources by relevance
            sources.sort(key=lambda x: x["relevance_score"], reverse=True)
            
            # Step 8: Smart source limiting
            if is_listing_query:
                # Listing query - show ALL sources (no limit)
                logger.info(f"📋 Listing query: showing all {len(sources)} document sources")
            elif selected_files is None:
                # General query - limit to top 10 most relevant sources
                logger.info(f"📊 General query: limiting to top 10 of {len(sources)} sources")
                sources = sources[:10]
            else:
                # Specific files query - show only selected files (no arbitrary limit)
                logger.info(f"📊 Specific query: showing {len(sources)} selected file sources")
            
            # Step 9: Generate final response using LLM with document context and conversation history
            context = "\n\n---\n\n".join(context_parts)
            response_text = await self.llm_service.generate_response(
                question, 
                context, 
                conversation_history=conversation_history or []
            )
            
            response_time = asyncio.get_event_loop().time() - start_time
            
            return QueryResult(
                message=response_text,
                sources=sources,
                response_time=round(response_time, 3),
                query_type=query_type,
                retrieval_count=retrieval_count,
                rerank_count=rerank_count
            )
            
        except Exception as e:
            logger.error(f"Query failed: {e}")
            response_time = asyncio.get_event_loop().time() - start_time
            return QueryResult(
                message=f"Sorry, I encountered an error while processing your query: {str(e)}",
                sources=[],
                response_time=round(response_time, 3),
                query_type="error",
                retrieval_count=retrieval_count if 'retrieval_count' in locals() else 0,
                rerank_count=rerank_count if 'rerank_count' in locals() else 0
            )
    
    def get_stats(self) -> Dict:
        """Get comprehensive stats"""
        try:
            collection_count = self.vector_store.get_collection_count()
            # file_metadata entries are dicts already; avoid __dict__ access
            return {
                "total_files": len(self.file_hashes),
                "total_chunks": collection_count,
                "current_directory": self.current_directory,
                "indexed_files": list(self.file_hashes.keys()),
                "file_metadata": {k: v for k, v in self.file_metadata.items()},
                "avg_chunks_per_file": (
                    collection_count / len(self.file_hashes)
                    if self.file_hashes else 0
                ),
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
            
            # Clear in-memory data
            self.file_hashes.clear()
            self.file_metadata.clear()
            
            logger.info("DocumentProcessorOrchestrator cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    async def clear_collection(self):
        """Clear all documents from the vector store and reset tracking"""
        try:
            # Clear vector store
            await self.vector_store.clear_collection()
            
            # Clear in-memory tracking
            self.file_hashes.clear()
            self.file_metadata.clear()
            
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
