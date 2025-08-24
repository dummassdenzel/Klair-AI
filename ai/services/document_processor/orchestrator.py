import asyncio
import logging
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
                 ollama_model: str = "tinyllama"):
        
        # Initialize all services
        self.text_extractor = TextExtractor()
        self.chunker = DocumentChunker(chunk_size, chunk_overlap)
        self.embedding_service = EmbeddingService(embed_model_name)
        self.vector_store = VectorStoreService(persist_dir)
        self.llm_service = LLMService(ollama_base_url, ollama_model)
        self.file_validator = FileValidator(max_file_size_mb)
        self.database_service = DatabaseService()
        
        # State tracking
        self.file_hashes: Dict[str, str] = {}
        self.file_metadata: Dict[str, FileMetadata] = {}
        self.current_directory: Optional[str] = None
        
        logger.info("DocumentProcessorOrchestrator initialized successfully")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
    
    async def initialize_from_directory(self, directory_path: str):
        """Initialize processor with documents from directory"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            dir_path = Path(directory_path)
            if not dir_path.exists():
                raise ValueError(f"Directory does not exist: {directory_path}")
            
            if not dir_path.is_dir():
                raise ValueError(f"Path is not a directory: {directory_path}")
            
            logger.info(f"Initializing from directory: {directory_path}")
            self.current_directory = directory_path
            
            # Clear existing data
            await self.vector_store.clear_collection()
            self.file_hashes.clear()
            self.file_metadata.clear()
            
            # Find all supported files
            supported_files = []
            for file_path in dir_path.rglob("*"):
                if file_path.is_file():
                    is_valid, error = self.file_validator.validate_file(str(file_path))
                    if is_valid:
                        supported_files.append(str(file_path))
                    elif error and "Unsupported file type" not in error:
                        logger.warning(f"Skipping {file_path}: {error}")
            
            if not supported_files:
                logger.warning(f"No supported files found in {directory_path}")
                return
            
            logger.info(f"Found {len(supported_files)} files to process")
            
            # Process files in batches for better memory management
            batch_size = 10
            processed = 0
            failed = 0
            
            for i in range(0, len(supported_files), batch_size):
                batch = supported_files[i:i + batch_size]
                
                # Process batch concurrently
                tasks = [self._process_single_file(file_path) for file_path in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Count results
                for result in results:
                    if isinstance(result, Exception):
                        failed += 1
                    else:
                        processed += 1
                
                logger.info(f"Processed {processed + failed}/{len(supported_files)} files")
            
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"Initialization complete: {processed} files processed, "
                       f"{failed} failed in {elapsed:.2f}s")
                
        except Exception as e:
            logger.error(f"Failed to initialize from directory: {e}")
            raise
    
    async def _process_single_file(self, file_path: str) -> ProcessingResult:
        """Process a single file (used in batch processing)"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            await self.add_document(file_path)
            processing_time = asyncio.get_event_loop().time() - start_time
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                chunks_created=len(self.file_metadata[file_path].chunks_count) if file_path in self.file_metadata else 0,
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
    
    async def add_document(self, file_path: str):
        """Add or update a document"""
        try:
            # Get real file metadata
            file_metadata = self.file_validator.extract_file_metadata(file_path)
            current_hash = self.file_validator.calculate_file_hash(file_path)
            
            # Process document...
            text = await self.text_extractor.extract_text_async(file_path)
            if not text or not text.strip():
                logger.warning(f"No text extracted from {file_path}")
                return
            
            chunks = self.chunker.create_chunks(text, file_path)
            embeddings = self.embedding_service.encode_texts([chunk.text for chunk in chunks])
            await self.vector_store.batch_insert_chunks(chunks, embeddings)
            
            # Store complete metadata in database
            await self.database_service.store_document_metadata(
                file_path=file_path,
                file_hash=current_hash,
                file_type=file_metadata["file_type"],
                file_size=file_metadata["size_bytes"],
                last_modified=file_metadata["modified_at"],
                content_preview=text[:500],
                chunks_count=len(chunks)
            )
            
            # Update tracking
            self.file_hashes[file_path] = current_hash
            self.file_metadata[file_path] = file_metadata
            
        except Exception as e:
            logger.error(f"Error processing document {file_path}: {e}")
            raise
    
    async def remove_document(self, file_path: str):
        """Remove document and clean up tracking"""
        try:
            await self.vector_store.remove_document_chunks(file_path)
            
            # Clean up tracking
            self.file_hashes.pop(file_path, None)
            self.file_metadata.pop(file_path, None)
            
            logger.info(f"Removed document: {file_path}")
            
        except Exception as e:
            logger.error(f"Error removing document {file_path}: {e}")
    
    async def query(self, question: str, max_results: int = 5) -> QueryResult:
        """Query the document index with LLM integration"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Generate query embedding
            query_embedding = self.embedding_service.encode_single_text(question)
            
            # Search vector store
            results = await self.vector_store.search_similar(query_embedding, max_results)
            
            if not results['documents'] or not results['documents'][0]:
                return QueryResult(
                    message="I don't have information about that in the current documents.",
                    sources=[],
                    response_time=asyncio.get_event_loop().time() - start_time
                )
            
            # Process results
            documents = results['documents'][0]
            metadatas = results['metadatas'][0] 
            distances = results['distances'][0]
            
            # Group chunks by file for better context
            file_chunks = {}
            for doc, metadata, distance in zip(documents, metadatas, distances):
                file_path = metadata.get("file_path", "Unknown")
                if file_path not in file_chunks:
                    file_chunks[file_path] = []
                file_chunks[file_path].append({
                    "text": doc,
                    "distance": distance,
                    "chunk_id": metadata.get("chunk_id", 0),
                    "metadata": metadata
                })
            
            # Create sources and context
            sources = []
            context_parts = []
            
            for file_path, chunks in file_chunks.items():
                # Sort chunks by chunk_id for proper order
                chunks.sort(key=lambda x: x["chunk_id"])
                
                # Combine chunks for this file
                file_text = "\n".join([chunk["text"] for chunk in chunks])
                context_parts.append(file_text)
                
                # Calculate average relevance (lower distance = higher relevance)
                avg_distance = sum(chunk["distance"] for chunk in chunks) / len(chunks)
                relevance_score = max(0, 1.0 - avg_distance)  # Convert to 0-1 score
                
                sources.append({
                    "file_path": file_path,
                    "relevance_score": round(relevance_score, 3),
                    "content_snippet": file_text[:300] + "..." if len(file_text) > 300 else file_text,
                    "chunks_found": len(chunks),
                    "file_type": chunks[0]["metadata"].get("file_type", "unknown")
                })
            
            # Sort sources by relevance
            sources.sort(key=lambda x: x["relevance_score"], reverse=True)
            
            # Generate response using LLM
            context = "\n\n---\n\n".join(context_parts)
            response_text = await self.llm_service.generate_response(question, context)
            
            response_time = asyncio.get_event_loop().time() - start_time
            
            return QueryResult(
                message=response_text,
                sources=sources,
                response_time=round(response_time, 3)
            )
            
        except Exception as e:
            logger.error(f"Query failed: {e}")
            response_time = asyncio.get_event_loop().time() - start_time
            return QueryResult(
                message=f"Sorry, I encountered an error while processing your query: {str(e)}",
                sources=[],
                response_time=round(response_time, 3)
            )
    
    def get_stats(self) -> Dict:
        """Get comprehensive stats"""
        try:
            collection_count = self.vector_store.get_collection_count()
            return {
                "total_files": len(self.file_hashes),
                "total_chunks": collection_count,
                "current_directory": self.current_directory,
                "indexed_files": list(self.file_hashes.keys()),
                "file_metadata": {k: v.__dict__ for k, v in self.file_metadata.items()},
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
