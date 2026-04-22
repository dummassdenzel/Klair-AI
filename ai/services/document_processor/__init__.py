"""
Document Processor Service Package

Modular, service-oriented architecture for processing documents and building a
RAG (Retrieval-Augmented Generation) system.

Architecture (Phase 7 decomposition):
- IndexingService       : file ingestion, chunking, embedding, storage
- RetrievalService      : hybrid search, context assembly
- QueryPipelineService  : routing, tool calling, planner, response generation
- DocumentProcessorOrchestrator : thin coordinator that wires all services

Usage:
    from services.document_processor import DocumentProcessorOrchestrator

    processor = DocumentProcessorOrchestrator()
    await processor.initialize_from_directory("/path/to/documents")
    result = await processor.query("What is this document about?")
"""

from .orchestrator import DocumentProcessorOrchestrator
from .indexing_service import IndexingService, MetadataCache
from .retrieval_service import RetrievalService
from .query_pipeline import QueryPipelineService
from .models import (
    DocumentChunk, QueryResult, FileMetadata, ProcessingResult,
)
from .extraction import TextExtractor, DocumentChunker, EmbeddingService, FileValidator
from .storage import VectorStoreService, BM25Service
from .llm import LLMService
from .retrieval import HybridSearchService, FilenameTrie
from .updates import (
    UpdateQueue, UpdateTask, UpdateResult, UpdatePriority, UpdateWorker
)

__all__ = [
    "DocumentProcessorOrchestrator",
    "IndexingService",
    "MetadataCache",
    "RetrievalService",
    "QueryPipelineService",
    "DocumentChunk",
    "QueryResult",
    "FileMetadata",
    "ProcessingResult",
    "TextExtractor",
    "DocumentChunker",
    "EmbeddingService",
    "VectorStoreService",
    "LLMService",
    "FileValidator",
    "BM25Service",
    "HybridSearchService",
    "UpdateQueue",
    "UpdateTask",
    "UpdateResult",
    "UpdatePriority",
    "UpdateWorker",
]
