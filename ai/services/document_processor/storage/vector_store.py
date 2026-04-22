import asyncio
import logging
import threading
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from ..models import DocumentChunk


logger = logging.getLogger(__name__)


class VectorStoreService:
    """Service for managing ChromaDB vector store operations"""

    def __init__(self, persist_dir: str = "./chroma_db"):
        self.persist_dir = persist_dir
        self.chroma_client = None
        self.collection = None
        self._lock = threading.Lock()

    def _initialize_client(self):
        """Initialize ChromaDB client and collection (lazy, thread-safe)."""
        if self.chroma_client is not None:
            return
        with self._lock:
            if self.chroma_client is not None:
                return
            try:
                import chromadb

                self.chroma_client = chromadb.PersistentClient(
                    path=self.persist_dir,
                    settings=chromadb.config.Settings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    ),
                )
                self.collection = self.chroma_client.get_or_create_collection(
                    name="documents",
                    metadata={"hnsw:space": "cosine"},
                )
                actual_space = (self.collection.metadata or {}).get("hnsw:space")
                if actual_space != "cosine":
                    logger.warning(
                        "ChromaDB collection 'documents' uses distance metric %r instead of "
                        "'cosine'. Similarity scores will be incorrect. Delete the chroma_db "
                        "directory and re-index.",
                        actual_space,
                    )
                logger.info(f"ChromaDB initialized at {self.persist_dir}")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB: {e}")
                raise

    async def batch_insert_chunks(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]],
    ):
        """Batch insert chunks into the vector store."""
        if not chunks or not embeddings:
            return

        try:
            ids = []
            documents = []
            metadatas = []
            for chunk, embedding in zip(chunks, embeddings):
                chunk_id = f"{chunk.file_path}_chunk_{chunk.chunk_id}"
                metadata = {
                    "file_path": chunk.file_path,
                    "file_type": chunk.file_path.split(".")[-1].lower(),
                    "chunk_id": chunk.chunk_id,
                    "total_chunks": chunk.total_chunks,
                    "start_pos": chunk.start_pos,
                    "end_pos": chunk.end_pos,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "text_length": len(chunk.text),
                }
                ids.append(chunk_id)
                documents.append(chunk.text)
                metadatas.append(metadata)

            def _insert():
                self._initialize_client()
                self.collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )

            await asyncio.to_thread(_insert)
            logger.info(f"Successfully inserted {len(chunks)} chunks")
        except Exception as e:
            logger.error(f"Error batch inserting chunks: {e}")
            raise

    async def search_similar(
        self,
        query_embedding: List[float],
        max_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ):
        """Search for similar documents. Optional where filters by metadata."""
        try:
            kwargs: Dict[str, Any] = dict(
                query_embeddings=[query_embedding],
                n_results=max_results,
                include=["documents", "metadatas", "distances"],
            )
            if where:
                kwargs["where"] = where

            def _query():
                self._initialize_client()
                return self.collection.query(**kwargs)

            return await asyncio.to_thread(_query)
        except Exception as e:
            logger.error(f"Error searching vector store: {e}")
            raise

    async def remove_document_chunks(self, file_path: str):
        """Remove all chunks for a document."""
        try:
            def _remove():
                self._initialize_client()
                results = self.collection.get(where={"file_path": file_path})
                if results["ids"]:
                    self.collection.delete(ids=results["ids"])
                    logger.debug(f"Removed {len(results['ids'])} chunks for {file_path}")

            await asyncio.to_thread(_remove)
        except Exception as e:
            logger.error(f"Error removing chunks for {file_path}: {e}")
            raise

    async def clear_collection(self):
        """Clear all documents from collection."""
        try:
            def _clear():
                self._initialize_client()
                all_results = self.collection.get()
                if all_results["ids"]:
                    self.collection.delete(ids=all_results["ids"])
                    logger.info(f"Cleared {len(all_results['ids'])} existing documents")

            await asyncio.to_thread(_clear)
        except Exception as e:
            logger.warning(f"Error clearing collection: {e}")

    def get_collection_count(self) -> int:
        """Get total number of documents in collection."""
        try:
            self._initialize_client()
            return self.collection.count()
        except Exception as e:
            logger.error(f"Error getting collection count: {e}")
            return 0

    def get_document_chunks(self, file_path: str):
        """Get all chunks for a specific document."""
        try:
            self._initialize_client()
            return self.collection.get(where={"file_path": file_path})
        except Exception as e:
            logger.error(f"Error getting chunks for {file_path}: {e}")
            return None

    def cleanup(self):
        """Release ChromaDB client resources."""
        try:
            if self.chroma_client is not None:
                close = getattr(self.chroma_client, "close", None)
                if callable(close):
                    close()
            self.chroma_client = None
            self.collection = None
        except Exception as e:
            logger.error(f"Error during vector store cleanup: {e}")
