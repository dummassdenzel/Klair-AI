"""
DocumentProcessorOrchestrator — thin coordinator (Phase 7 refactoring).

Constructs all primitive services, composes the three focused services:
  - IndexingService  : file ingestion, chunking, embedding, storage
  - RetrievalService : hybrid search, reranking, context assembly
  - QueryPipelineService : routing, tool calling, planner, response generation

Then exposes a single stable public API that callers (routers, file monitor)
depend on; every method is a one-line delegation.

Target: ≤ 300 lines.  No business logic lives here.
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from .models import QueryResult
from .extraction.text_extractor import TextExtractor
from .extraction.chunker import DocumentChunker
from .extraction.embedding_service import EmbeddingService
from .extraction.file_validator import FileValidator
from .extraction.ocr_service import OCRService
from .storage.vector_store import VectorStoreService
from .storage.bm25_service import BM25Service
from .llm.llm_service import LLMService
from .retrieval.hybrid_search import HybridSearchService
from .retrieval.reranker_service import ReRankingService
from .updates.update_queue import UpdateQueue
from .updates.update_executor import UpdateExecutor
from .updates.update_worker import UpdateWorker
from .updates.chunk_differ import ChunkDiffer
from .updates.update_strategy import UpdateStrategySelector
from .query_config import RetrievalConfig, default_retrieval_config
from .indexing_service import IndexingService
from .retrieval_service import RetrievalService
from .query_pipeline import QueryPipelineService
from database import DatabaseService
from ..routing import Router, QueryClassifier


logger = logging.getLogger(__name__)


class DocumentProcessorOrchestrator:
    """
    Thin coordinator that constructs and wires all services.

    External callers (routers, file monitor) interact only with this class;
    they are unaffected by the internal decomposition.
    """

    def __init__(
        self,
        persist_dir: str = "./chroma_db",
        embed_model_name: str = "BAAI/bge-small-en-v1.5",
        max_file_size_mb: int = 50,
        chunk_size: int = 300,       # tokens
        chunk_overlap: int = 50,     # tokens
        max_chunk_tokens: int = 512,
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "tinyllama",
        gemini_api_key: Optional[str] = None,
        gemini_model: str = "gemini-2.5-pro",
        groq_api_key: Optional[str] = None,
        groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        llm_provider: str = "ollama",
    ) -> None:
        # ── OCR (optional) ────────────────────────────────────────────────────
        try:
            import sys
            from pathlib import Path as _Path

            ai_dir = _Path(__file__).parent.parent.parent.parent
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

        # ── Primitive services ────────────────────────────────────────────────
        self.text_extractor = TextExtractor(ocr_service=ocr_service)
        self.chunker = DocumentChunker(chunk_size, chunk_overlap, max_tokens=max_chunk_tokens)
        self.embedding_service = EmbeddingService(embed_model_name)
        self.vector_store = VectorStoreService(persist_dir)
        self.llm_service = LLMService(
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            groq_api_key=groq_api_key,
            groq_model=groq_model,
            provider=llm_provider,
        )
        self.file_validator = FileValidator(max_file_size_mb, ocr_service=ocr_service)
        self.database_service = DatabaseService()
        self.bm25_service = BM25Service(persist_dir)
        self.hybrid_search = HybridSearchService(k=60)
        self.reranker = ReRankingService(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.retrieval_config: RetrievalConfig = default_retrieval_config

        # ── UpdateWorker stack ────────────────────────────────────────────────
        # Single UpdateQueue shared by UpdateWorker and IndexingService.
        _update_queue = UpdateQueue(max_queue_size=1000)

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
        _update_worker = UpdateWorker(
            update_queue=_update_queue,
            update_executor=self.update_executor,
            chunk_differ=self.chunk_differ,
            strategy_selector=self.strategy_selector,
            chunker=self.chunker,
            text_extractor=self.text_extractor,
        )

        # ── Composed services ─────────────────────────────────────────────────
        self.indexing = IndexingService(
            text_extractor=self.text_extractor,
            file_validator=self.file_validator,
            chunker=self.chunker,
            embedding_service=self.embedding_service,
            vector_store=self.vector_store,
            bm25_service=self.bm25_service,
            database_service=self.database_service,
            update_queue=_update_queue,
            update_executor=self.update_executor,
            update_worker=_update_worker,
            chunk_differ=self.chunk_differ,
            strategy_selector=self.strategy_selector,
        )

        self.retrieval = RetrievalService(
            embedding_service=self.embedding_service,
            vector_store=self.vector_store,
            bm25_service=self.bm25_service,
            hybrid_search=self.hybrid_search,
            reranker=self.reranker,
            llm_service=self.llm_service,
            retrieval_config=self.retrieval_config,
            filename_trie=self.indexing.filename_trie,  # shared reference
        )

        _router = Router(QueryClassifier(self.llm_service))
        self.pipeline = QueryPipelineService(
            llm_service=self.llm_service,
            embedding_service=self.embedding_service,
            router=_router,
            retrieval_service=self.retrieval,
        )

        logger.info(
            "DocumentProcessorOrchestrator initialized with hybrid search "
            "(semantic + keyword) and incremental updates"
        )

    # ── Pass-through properties ───────────────────────────────────────────────

    @property
    def is_initializing(self) -> bool:
        return self.indexing.is_initializing

    @property
    def files_being_processed(self) -> set:
        return self.indexing.files_being_processed

    @property
    def filename_trie(self):
        return self.indexing.filename_trie

    @property
    def update_queue(self):
        return self.indexing.update_queue

    @property
    def current_directory(self) -> Optional[str]:
        return self.indexing.current_directory

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def initialize(self) -> None:
        """Start background initialization tasks (metadata loader + update worker)."""
        await self.indexing.initialize()

    # ── Indexing delegation ───────────────────────────────────────────────────

    def set_post_index_hook(self, hook) -> None:
        self.indexing.set_post_index_hook(hook)

    async def cancel_background_work(self) -> None:
        await self.indexing.cancel_background_work()

    async def initialize_from_directory(
        self, directory_path: str, resume_mode: bool = False
    ) -> None:
        await self.indexing.initialize_from_directory(directory_path, resume_mode)

    async def add_document(
        self, file_path: str, force_reindex: bool = False, use_queue: bool = True
    ) -> None:
        await self.indexing.add_document(file_path, force_reindex, use_queue)

    async def remove_document(self, file_path: str) -> None:
        await self.indexing.remove_document(file_path)

    async def enqueue_update(
        self,
        file_path: str,
        update_type: str = "modified",
        user_requested: bool = False,
    ) -> bool:
        return await self.indexing.enqueue_update(file_path, update_type, user_requested)

    # ── Query delegation ──────────────────────────────────────────────────────

    async def query(
        self, question: str, max_results: int = 15, conversation_history: list = None
    ) -> QueryResult:
        return await self.pipeline.query(question, max_results, conversation_history)

    async def query_stream(
        self, question: str, max_results: int = 15, conversation_history: list = None
    ) -> AsyncIterator[Tuple[str, Any]]:
        async for event in self.pipeline.query_stream(question, max_results, conversation_history):
            yield event

    async def build_conversation_history(
        self,
        message_pairs: List[Dict[str, str]],
        session_id: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        return await self.pipeline.build_conversation_history(message_pairs, session_id)

    # ── Data management ───────────────────────────────────────────────────────

    async def clear_all_data(self) -> None:
        """Clear all indexed data: update queue, vector store, BM25, trie, router cache, DB."""
        logger.info("Clearing all indexed data...")

        if hasattr(self, "update_queue"):
            await self.update_queue.clear()
            logger.info("Update queue cleared")

        await self.vector_store.clear_collection()
        self.indexing._metadata_cache.clear()
        self.indexing.files_being_processed.clear()
        logger.info("Vector store cleared")

        self.bm25_service.clear()
        logger.info("BM25 index cleared")

        self.indexing.filename_trie.clear()
        logger.info("Filename Trie cleared")

        self.pipeline.router.clear_cache()

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

    async def clear_collection(self) -> None:
        """Clear all documents from the vector store and reset tracking."""
        try:
            await self.vector_store.clear_collection()
            self.indexing._metadata_cache.clear()
            self.pipeline.router.clear_cache()
            logger.info("Document collection cleared successfully")
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")
            raise

    # ── Status & stats ────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """Check if basic services are initialized."""
        try:
            return (
                self.text_extractor is not None
                and self.chunker is not None
                and self.file_validator is not None
            )
        except Exception:
            return False

    async def get_stats(self) -> Dict:
        """Return comprehensive stats (DB totals, a small sample of paths for the UI)."""
        try:
            collection_count = self.vector_store.get_collection_count()
            db_stats = await self.database_service.get_document_stats()
            total_files = db_stats.get("total_documents", 0) or 0
            indexed_files_sample = await self.database_service.get_indexed_file_paths(limit=20)
            return {
                "total_files": total_files,
                "total_chunks": collection_count,
                "current_directory": self.indexing.current_directory,
                "indexed_files_count": total_files,
                "indexed_files": indexed_files_sample,
                "metadata_cache_size": len(self.indexing._metadata_cache),
                "avg_chunks_per_file": (collection_count / total_files) if total_files else 0,
                "embedding_model": self.embedding_service.model_name,
                "chunk_size": self.chunker.chunk_size,
                "chunk_overlap": self.chunker.chunk_overlap,
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}

    def get_llm_token_usage(self) -> Dict[str, int]:
        """Expose cumulative LLM token usage for monitoring (mainly Groq)."""
        try:
            return self.llm_service.get_token_usage()
        except Exception:
            return {"prompt": 0, "completion": 0, "total": 0}

    async def cleanup(self) -> None:
        """Release all resources."""
        try:
            await self.llm_service.cleanup()
            self.vector_store.cleanup()
            self.embedding_service.cleanup()
            self.indexing._metadata_cache.clear()
            logger.info("DocumentProcessorOrchestrator cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
