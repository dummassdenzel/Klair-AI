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
from .extraction import TextExtractor, DocumentChunker, EmbeddingService, FileValidator
from .storage import VectorStoreService, BM25Service
from .llm import LLMService
from .retrieval import HybridSearchService, ReRankingService, FilenameTrie
from .updates import (
    ChunkDiffer, UpdateStrategy, UpdateStrategySelector, StrategySelectionResult,
    UpdateQueue, UpdateTask, UpdateResult, UpdatePriority,
    UpdateExecutor, Checkpoint, UpdateWorker
)
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
