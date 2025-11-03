from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class DocumentChunk:
    """Represents a chunk of text from a document"""
    text: str
    chunk_id: int
    total_chunks: int
    file_path: str
    start_pos: int
    end_pos: int


@dataclass 
class QueryResult:
    """Result from a document query"""
    message: str
    sources: List[Dict]
    response_time: float
    query_type: Optional[str] = None  # greeting, general, document
    retrieval_count: Optional[int] = None  # Number of chunks retrieved
    rerank_count: Optional[int] = None  # Number of chunks re-ranked


@dataclass
class FileMetadata:
    """Metadata about a processed file"""
    file_path: str
    file_type: str
    size_bytes: int
    modified_at: datetime
    chunks_count: int
    processing_status: str
    last_processed: datetime
    hash: str


@dataclass
class ProcessingResult:
    """Result from processing a document"""
    success: bool
    file_path: str
    chunks_created: int
    error_message: Optional[str] = None
    processing_time: Optional[float] = None
