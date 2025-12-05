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
from .query_config import RetrievalConfig, default_retrieval_config
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
        
        # Retrieval configuration
        self.retrieval_config = default_retrieval_config
        
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
            if not self.file_metadata:
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
    
    async def _classify_query(self, question: str, conversation_history: list = None) -> str:
        """
        Unified query classification.
        
        Returns:
            'greeting' - Simple greetings
            'general' - General questions not about documents
            'document_listing' - Requests to list/show all documents
            'document_search' - Questions requiring document retrieval
        """
        try:
            # Build conversation context
            conversation_context = ""
            if conversation_history:
                conversation_context = "\n\nRecent conversation:\n"
                for msg in conversation_history[-2:]:
                    role = "User" if msg["role"] == "user" else "Assistant"
                    conversation_context += f"{role}: {msg['content'][:150]}...\n"
            
            classification_prompt = f"""Classify this query into ONE category:

{conversation_context}
USER QUERY: "{question}"

CATEGORIES:
1. greeting - Greetings, pleasantries ("hello", "hi", "thanks", "goodbye")
2. general - Questions about the AI itself, not documents ("what can you do?", "how does this work?")
3. document_listing - Requests to list/show documents ("what files do we have?", "list all documents", "show me all PDFs")
4. document_search - Questions requiring document content ("what's in sales_report.pdf?", "who attended?", "list all speakers")

IMPORTANT:
- If query contains pronouns (that, it, this) or references previous context → document_search
- If query asks to "list" or "show" documents/files → document_listing
- If query asks about document CONTENT → document_search

Respond with ONLY ONE WORD: greeting, general, document_listing, or document_search"""

            response = await self.llm_service.generate_simple(classification_prompt)
            classification = response.strip().lower()
            
            # Validate and default to document_search if uncertain
            valid_types = ['greeting', 'general', 'document_listing', 'document_search']
            if classification not in valid_types:
                logger.warning(f"Invalid classification '{classification}', defaulting to document_search")
                return 'document_search'
            
            logger.info(f"Query classified as: {classification}")
            return classification
            
        except Exception as e:
            logger.error(f"Classification failed: {e}, defaulting to document_search")
            return 'document_search'
    
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
    
    async def _retrieve_chunks(self, query: str, query_type: str, explicit_filename: Optional[str] = None) -> tuple:
        """
        Single retrieval pipeline for all document queries.
        
        Args:
            query: Search query
            query_type: Query classification type
            explicit_filename: Explicit filename if detected, None otherwise
            
        Returns:
            (documents, metadatas, scores, retrieval_count, rerank_count)
        """
        # Get retrieval parameters
        params = self.retrieval_config.get_retrieval_params(query_type, False)
        
        top_k = params['top_k']
        rerank_top_k = params['rerank_top_k']
        final_top_k = params['final_top_k']
        
        logger.info(f"Retrieval params: top_k={top_k}, rerank_top_k={rerank_top_k}, final_top_k={final_top_k}")
        
        # Step 1: Semantic search
        query_embedding = self.embedding_service.encode_single_text(query)
        semantic_results = await self.vector_store.search_similar(query_embedding, top_k)
        
        if not semantic_results['documents'] or not semantic_results['documents'][0]:
            return ([], [], [], 0, 0)
        
        # Step 2: BM25 boost
        bm25_results = self.bm25_service.search(query, top_k=top_k)
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
        
        # Step 4: Re-ranking (if enabled)
        rerank_count = 0
        if rerank_top_k > 0 and len(documents) > final_top_k:
            logger.info(f"🔄 Re-ranking top {min(rerank_top_k, len(documents))} of {len(documents)} results...")
            
            docs_to_rerank = documents[:min(rerank_top_k, len(documents))]
            metas_to_rerank = metadatas[:min(rerank_top_k, len(metadatas))]
            scores_to_rerank = scores[:min(rerank_top_k, len(scores))]
            
            reranked_docs, reranked_metas, reranked_scores = self.reranker.rerank_with_metadata(
                query=query,
                documents=docs_to_rerank,
                metadata_list=metas_to_rerank,
                scores_list=scores_to_rerank,
                top_k=final_top_k
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
    
    async def query(self, question: str, max_results: int = 15, conversation_history: list = None) -> QueryResult:
        """
        Query the document index using unified retrieval pipeline.
        
        All document queries flow through the same pipeline:
        1. Classify query (greeting/general/document_listing/document_search)
        2. For document_listing: use database listing
        3. For document_search: use single retrieval pipeline (semantic + BM25 + reranking)
        4. Generate response with enhanced prompts for comprehensive extraction
        
        No special cases or pattern matching - configuration-driven approach.
        """
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
            
            # Use original question for retrieval - modern LLMs handle context natively
            retrieval_query = question
            
            # Handle document_listing queries
            if query_type == 'document_listing':
                result = await self._get_document_listing()
                result.response_time = asyncio.get_event_loop().time() - start_time
                return result
            
            # Document search - check for explicit filename
            explicit_filename = self._find_explicit_filename(question)
            selected_files = await self._select_relevant_files(question)
            
            # Retrieve chunks using single pipeline
            documents, metadatas, scores, retrieval_count, rerank_count = await self._retrieve_chunks(
                retrieval_query, query_type, explicit_filename
            )
            
            if not documents:
                return QueryResult(
                    message="I don't have information about that in the current documents.",
                    sources=[],
                    response_time=asyncio.get_event_loop().time() - start_time,
                    query_type=query_type,
                    retrieval_count=0,
                    rerank_count=0
                )
            
            # If explicit files selected, prioritize their chunks
            if selected_files:
                prioritized_docs = []
                prioritized_metas = []
                prioritized_scores = []
                other_docs = []
                other_metas = []
                other_scores = []
                
                for doc, meta, score in zip(documents, metadatas, scores):
                    file_path = meta.get("file_path", "")
                    if any(sf in file_path for sf in selected_files):
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
                
                logger.info(f"✅ Prioritized {len(prioritized_docs)} chunks from {len(selected_files)} selected files")
            
            # Group chunks by file
            file_chunks = {}
            for doc, metadata, score in zip(documents, metadatas, scores):
                file_path = metadata.get("file_path", "Unknown")
                if file_path not in file_chunks:
                    file_chunks[file_path] = []
                file_chunks[file_path].append({
                    "text": doc,
                    "score": score,
                    "chunk_id": metadata.get("chunk_id", 0),
                    "metadata": metadata
                })
            
            # Build context and sources
            sources = []
            context_parts = []
            
            # Filter files if explicit selection
            files_to_process = file_chunks.items()
            if selected_files:
                selected_file_chunks = {fp: chunks for fp, chunks in file_chunks.items() if any(sf in fp for sf in selected_files)}
                files_to_process = list(selected_file_chunks.items())
                logger.info(f"🎯 Focusing on {len(selected_file_chunks)} selected file(s)")
            
            for file_path, chunks in files_to_process:
                chunks.sort(key=lambda x: x["chunk_id"])
                filename = Path(file_path).name
                file_text = "\n".join([chunk["text"] for chunk in chunks])
                
                context_parts.append(f"[Document: {filename}]\n{file_text}")
                
                avg_score = sum(chunk["score"] for chunk in chunks) / len(chunks)
                relevance_score = min(1.0, avg_score * 50)
                
                sources.append({
                    "file_path": file_path,
                    "relevance_score": round(relevance_score, 3),
                    "content_snippet": file_text[:300] + "..." if len(file_text) > 300 else file_text,
                    "chunks_found": len(chunks),
                    "file_type": chunks[0]["metadata"].get("file_type", "unknown")
                })
            
            sources.sort(key=lambda x: x["relevance_score"], reverse=True)
            
            # Limit sources
            source_limit = self.retrieval_config.get_source_limit(query_type, explicit_filename is not None)
            sources = sources[:source_limit]
            
            # Generate response with enhanced prompt for comprehensive extraction
            context = "\n\n---\n\n".join(context_parts)
            
            # Enhanced prompt instructions are handled in LLM service, but we can add a note
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
