import logging
from typing import List, Dict, Optional
from datetime import datetime
from .models import DocumentChunk


logger = logging.getLogger(__name__)


class VectorStoreService:
    """Service for managing ChromaDB vector store operations"""
    
    def __init__(self, persist_dir: str = "./chroma_db"):
        self.persist_dir = persist_dir
        self.chroma_client = None
        self.collection = None
        # Don't initialize immediately - use lazy loading
    
    def _initialize_client(self):
        """Initialize ChromaDB client and collection (lazy loading)"""
        if self.chroma_client is not None:
            return  # Already initialized
        
        try:
            # Import here to avoid startup issues
            import chromadb
            
            # Initialize ChromaDB with better settings
            self.chroma_client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=chromadb.config.Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            
            self.collection = self.chroma_client.get_or_create_collection(
                name="documents",
                metadata={
                    "hnsw:space": "cosine"
                }
            )
            
            logger.info(f"ChromaDB initialized at {self.persist_dir}")
            
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            raise
    
    async def batch_insert_chunks(self, chunks: List[DocumentChunk], embeddings: List[List[float]]):
        """Batch insert chunks efficiently"""
        if not chunks or not embeddings:
            return
        
        try:
            # Initialize client if needed
            self._initialize_client()
            
            # Prepare batch data
            ids = []
            documents = []
            metadatas = []
            
            for chunk, embedding in zip(chunks, embeddings):
                chunk_id = f"{chunk.file_path}_chunk_{chunk.chunk_id}"
                
                metadata = {
                    "file_path": chunk.file_path,
                    "file_type": chunk.file_path.split('.')[-1].lower(),
                    "chunk_id": chunk.chunk_id,
                    "total_chunks": chunk.total_chunks,
                    "start_pos": chunk.start_pos,
                    "end_pos": chunk.end_pos,
                    "processed_at": datetime.now().isoformat(),
                    "text_length": len(chunk.text)
                }
                
                ids.append(chunk_id)
                documents.append(chunk.text)
                metadatas.append(metadata)
            
            # Batch upsert
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
            logger.info(f"Successfully inserted {len(chunks)} chunks")
            
        except Exception as e:
            logger.error(f"Error batch inserting chunks: {e}")
            raise
    
    async def search_similar(self, query_embedding: List[float], max_results: int = 5):
        """Search for similar documents"""
        try:
            # Initialize client if needed
            self._initialize_client()
            
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=max_results,
                include=['documents', 'metadatas', 'distances']
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching vector store: {e}")
            raise
    
    async def remove_document_chunks(self, file_path: str):
        """Remove all chunks for a document"""
        try:
            # Initialize client if needed
            self._initialize_client()
            
            results = self.collection.get(where={"file_path": file_path})
            if results['ids']:
                self.collection.delete(ids=results['ids'])
                logger.debug(f"Removed {len(results['ids'])} chunks for {file_path}")
        except Exception as e:
            logger.error(f"Error removing chunks for {file_path}: {e}")
            raise
    
    async def clear_collection(self):
        """Clear all documents from collection"""
        try:
            # Initialize client if needed
            self._initialize_client()
            
            all_results = self.collection.get()
            if all_results['ids']:
                self.collection.delete(ids=all_results['ids'])
                logger.info(f"Cleared {len(all_results['ids'])} existing documents")
        except Exception as e:
            logger.warning(f"Error clearing collection: {e}")
    
    def get_collection_count(self) -> int:
        """Get total number of documents in collection"""
        try:
            # Initialize client if needed
            self._initialize_client()
            
            return self.collection.count()
        except Exception as e:
            logger.error(f"Error getting collection count: {e}")
            return 0
    
    def get_document_chunks(self, file_path: str):
        """Get all chunks for a specific document"""
        try:
            # Initialize client if needed
            self._initialize_client()
            
            return self.collection.get(where={"file_path": file_path})
        except Exception as e:
            logger.error(f"Error getting chunks for {file_path}: {e}")
            return None
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            if self.chroma_client:
                self.chroma_client = None
            if self.collection:
                self.collection = None
        except Exception as e:
            logger.error(f"Error during vector store cleanup: {e}")
