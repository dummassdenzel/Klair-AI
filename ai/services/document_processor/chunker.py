from typing import List
from .models import DocumentChunk


class DocumentChunker:
    """Service for creating semantic chunks from document text"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def create_chunks(self, text: str, file_path: str) -> List[DocumentChunk]:
        """Create semantic chunks with better boundary detection"""
        if len(text) <= self.chunk_size:
            return [DocumentChunk(
                text=text,
                chunk_id=0,
                total_chunks=1,
                file_path=file_path,
                start_pos=0,
                end_pos=len(text)
            )]
        
        chunks = []
        start = 0
        chunk_id = 0
        
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            
            # Find semantic boundary
            if end < len(text):
                end = self._find_chunk_boundary(text, start, end)
            
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(DocumentChunk(
                    text=chunk_text,
                    chunk_id=chunk_id,
                    total_chunks=0,  # Will be updated later
                    file_path=file_path,
                    start_pos=start,
                    end_pos=end
                ))
                chunk_id += 1
            
            # Next start with overlap
            start = max(start + 1, end - self.chunk_overlap)
            if start >= len(text):
                break
        
        # Update total_chunks
        for chunk in chunks:
            chunk.total_chunks = len(chunks)
        
        return chunks
    
    def _find_chunk_boundary(self, text: str, start: int, end: int) -> int:
        """Find optimal chunk boundary"""
        # Look for sentence endings
        for i in range(end - 1, max(start + self.chunk_size - 100, start), -1):
            if text[i] in '.!?':
                # Check if it's not an abbreviation
                if i + 1 < len(text) and text[i + 1].isspace():
                    return i + 1
        
        # Look for paragraph breaks
        for i in range(end - 1, max(start + self.chunk_size - 50, start), -1):
            if text[i] == '\n' and (i + 1 >= len(text) or text[i + 1] == '\n'):
                return i + 1
        
        # Look for any whitespace
        for i in range(end - 1, max(start + self.chunk_size - 20, start), -1):
            if text[i].isspace():
                return i + 1
        
        return end
