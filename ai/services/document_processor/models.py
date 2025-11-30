from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum


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


@dataclass
class ChunkMatch:
    """Represents a match between an old and new chunk"""
    old_chunk: DocumentChunk
    new_chunk: DocumentChunk
    similarity_score: float  # 0.0 to 1.0
    match_type: str  # "exact" (hash match), "similar" (embedding match), "text" (difflib match)


@dataclass
class ChunkDiffResult:
    """Result from comparing old and new chunks"""
    unchanged_chunks: List[ChunkMatch]  # Chunks that are identical (hash match)
    modified_chunks: List[ChunkMatch]  # Chunks that changed but are similar
    added_chunks: List[DocumentChunk]  # New chunks not in old version
    removed_chunks: List[DocumentChunk]  # Old chunks not in new version
    
    def get_change_percentage(self) -> float:
        """
        Calculate percentage of old chunks that changed.
        
        Note: Added chunks are not counted as "changes" to old chunks,
        they are new content. Only modified and removed chunks count as changes.
        """
        total_old = len(self.unchanged_chunks) + len(self.modified_chunks) + len(self.removed_chunks)
        if total_old == 0:
            # If no old chunks, check if there are new chunks
            if len(self.added_chunks) == 0:
                return 0.0  # Both empty = no change
            return 1.0  # All new (100% of old chunks are new, since there are none)
        # Only count modified and removed as "changes" to old chunks
        # Added chunks are new content, not changes to existing content
        changed = len(self.modified_chunks) + len(self.removed_chunks)
        return changed / total_old
    
    def get_total_changed_count(self) -> int:
        """Get total number of chunks that changed"""
        return len(self.modified_chunks) + len(self.added_chunks) + len(self.removed_chunks)