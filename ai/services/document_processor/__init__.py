"""
Document Processor Service Package

This package provides a modular, service-oriented architecture for processing documents
and building a RAG (Retrieval-Augmented Generation) system.

Services:
- TextExtractor: Handles text extraction from various file formats
- DocumentChunker: Creates semantic chunks from document text
- EmbeddingService: Manages document embeddings using sentence transformers
- VectorStoreService: Handles ChromaDB vector store operations
- LLMService: Manages LLM interactions via Ollama
- FileValidator: Validates files and extracts metadata
- DocumentProcessorOrchestrator: Main orchestrator that coordinates all services

Usage:
    from services.document_processor import DocumentProcessorOrchestrator
    
    processor = DocumentProcessorOrchestrator()
    await processor.initialize_from_directory("/path/to/documents")
    result = await processor.query("What is this document about?")
"""

from .orchestrator import DocumentProcessorOrchestrator
from .models import (
    DocumentChunk, QueryResult, FileMetadata, ProcessingResult,
    ChunkMatch, ChunkDiffResult
)
from .text_extractor import TextExtractor
from .chunker import DocumentChunker
from .embedding_service import EmbeddingService
from .vector_store import VectorStoreService
from .llm_service import LLMService
from .file_validator import FileValidator
from .bm25_service import BM25Service
from .hybrid_search import HybridSearchService
from .reranker_service import ReRankingService
from .chunk_differ import ChunkDiffer
from .update_strategy import UpdateStrategy, UpdateStrategySelector, StrategySelectionResult
from .update_queue import UpdateQueue, UpdateTask, UpdateResult, UpdatePriority
from .update_executor import UpdateExecutor, Checkpoint
from .update_worker import UpdateWorker
from .config import config, DocumentProcessorConfig

__all__ = [
    "DocumentProcessorOrchestrator",
    "DocumentChunk",
    "QueryResult", 
    "FileMetadata",
    "ProcessingResult",
    "ChunkMatch",
    "ChunkDiffResult",
    "TextExtractor",
    "DocumentChunker",
    "EmbeddingService",
    "VectorStoreService",
    "LLMService",
    "FileValidator",
    "BM25Service",
    "HybridSearchService",
    "ReRankingService",
    "ChunkDiffer",
    "UpdateStrategy",
    "UpdateStrategySelector",
    "StrategySelectionResult",
    "UpdateQueue",
    "UpdateTask",
    "UpdateResult",
    "UpdatePriority",
    "UpdateExecutor",
    "Checkpoint",
    "UpdateWorker",
    "config",
    "DocumentProcessorConfig"
]

# For backward compatibility, you can still import the old way
DocumentProcessor = DocumentProcessorOrchestrator
