"""
Chunk Differ Service

Compares old and new document chunks to identify:
- Unchanged chunks (exact matches)
- Modified chunks (similar but changed)
- Added chunks (new in new version)
- Removed chunks (present in old but not new)

Uses a hybrid approach:
1. Hash-based matching for fast exact matches
2. Text similarity (difflib) for changed regions
3. Embedding-based similarity for semantic matching
"""

import logging
import hashlib
import difflib
from typing import List, Tuple, Set, Dict
import numpy as np

from .models import DocumentChunk, ChunkMatch, ChunkDiffResult
from .embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class ChunkDiffer:
    """Service for comparing document chunks to identify changes"""
    
    def __init__(
        self, 
        embedding_service: EmbeddingService,
        similarity_threshold: float = 0.85,
        text_similarity_threshold: float = 0.70
    ):
        """
        Initialize ChunkDiffer
        
        Args:
            embedding_service: Service for generating embeddings
            similarity_threshold: Minimum cosine similarity for chunk matching (0.0-1.0)
            text_similarity_threshold: Minimum text similarity (difflib ratio) for matching
        """
        self.embedding_service = embedding_service
        self.similarity_threshold = similarity_threshold
        self.text_similarity_threshold = text_similarity_threshold
        logger.info(f"ChunkDiffer initialized with similarity_threshold={similarity_threshold}")
    
    def diff_chunks(
        self, 
        old_chunks: List[DocumentChunk], 
        new_chunks: List[DocumentChunk]
    ) -> ChunkDiffResult:
        """
        Compare old and new chunks to identify changes.
        
        Args:
            old_chunks: List of chunks from previous version
            new_chunks: List of chunks from new version
            
        Returns:
            ChunkDiffResult with unchanged, modified, added, and removed chunks
        """
        if not old_chunks and not new_chunks:
            return ChunkDiffResult([], [], [], [])
        
        if not old_chunks:
            # All chunks are new
            return ChunkDiffResult([], [], new_chunks, [])
        
        if not new_chunks:
            # All chunks were removed
            return ChunkDiffResult([], [], [], old_chunks)
        
        logger.debug(f"Comparing {len(old_chunks)} old chunks with {len(new_chunks)} new chunks")
        
        # Step 1: Fast hash-based matching for exact matches
        unchanged_matches, unmatched_old, unmatched_new = self._hash_match(old_chunks, new_chunks)
        logger.debug(f"Hash matching: {len(unchanged_matches)} exact matches, "
                    f"{len(unmatched_old)} unmatched old, {len(unmatched_new)} unmatched new")
        
        # Step 2: Text similarity matching for changed chunks (fast, no embeddings needed)
        text_matches, remaining_old, remaining_new = self._text_similarity_match(
            unmatched_old, unmatched_new
        )
        logger.debug(f"Text similarity matching: {len(text_matches)} matches, "
                    f"{len(remaining_old)} remaining old, {len(remaining_new)} remaining new")
        
        # Step 3: Embedding-based similarity for semantic matching (slower but more accurate)
        embedding_matches, final_old, final_new = self._embedding_similarity_match(
            remaining_old, remaining_new
        )
        logger.debug(f"Embedding similarity matching: {len(embedding_matches)} matches, "
                    f"{len(final_old)} remaining old, {len(final_new)} remaining new")
        
        # Combine all matches
        all_matches = unchanged_matches + text_matches + embedding_matches
        
        # Separate into unchanged and modified
        unchanged = [m for m in all_matches if m.match_type == "exact"]
        modified = [m for m in all_matches if m.match_type in ["similar", "text"]]
        
        # Remaining chunks are added/removed
        added = final_new
        removed = final_old
        
        result = ChunkDiffResult(
            unchanged_chunks=unchanged,
            modified_chunks=modified,
            added_chunks=added,
            removed_chunks=removed
        )
        
        change_pct = result.get_change_percentage()
        logger.info(f"Chunk diff complete: {len(unchanged)} unchanged, {len(modified)} modified, "
                   f"{len(added)} added, {len(removed)} removed ({change_pct:.1%} changed)")
        
        return result
    
    def _hash_match(
        self, 
        old_chunks: List[DocumentChunk], 
        new_chunks: List[DocumentChunk]
    ) -> Tuple[List[ChunkMatch], List[DocumentChunk], List[DocumentChunk]]:
        """
        Fast hash-based matching for exact chunk matches.
        
        Returns:
            Tuple of (matches, unmatched_old_chunks, unmatched_new_chunks)
        """
        # Create hash map of old chunks
        old_hash_map: Dict[int, List[DocumentChunk]] = {}
        for chunk in old_chunks:
            chunk_hash = self._chunk_hash(chunk.text)
            if chunk_hash not in old_hash_map:
                old_hash_map[chunk_hash] = []
            old_hash_map[chunk_hash].append(chunk)
        
        matches = []
        matched_old_indices: Set[int] = set()
        matched_new_indices: Set[int] = set()
        
        # Match new chunks to old chunks by hash
        for i, new_chunk in enumerate(new_chunks):
            chunk_hash = self._chunk_hash(new_chunk.text)
            if chunk_hash in old_hash_map:
                # Find best matching old chunk (by position if multiple have same hash)
                best_match = None
                best_distance = float('inf')
                
                for old_chunk in old_hash_map[chunk_hash]:
                    # Prefer chunks at similar positions
                    distance = abs(old_chunk.chunk_id - new_chunk.chunk_id)
                    if distance < best_distance:
                        best_distance = distance
                        best_match = old_chunk
                
                if best_match:
                    old_idx = old_chunks.index(best_match)
                    if old_idx not in matched_old_indices:
                        matches.append(ChunkMatch(
                            old_chunk=best_match,
                            new_chunk=new_chunk,
                            similarity_score=1.0,
                            match_type="exact"
                        ))
                        matched_old_indices.add(old_idx)
                        matched_new_indices.add(i)
        
        # Get unmatched chunks
        unmatched_old = [old_chunks[i] for i in range(len(old_chunks)) if i not in matched_old_indices]
        unmatched_new = [new_chunks[i] for i in range(len(new_chunks)) if i not in matched_new_indices]
        
        return matches, unmatched_old, unmatched_new
    
    def _text_similarity_match(
        self,
        old_chunks: List[DocumentChunk],
        new_chunks: List[DocumentChunk]
    ) -> Tuple[List[ChunkMatch], List[DocumentChunk], List[DocumentChunk]]:
        """
        Match chunks using text similarity (difflib.SequenceMatcher).
        Fast but less accurate than embedding-based matching.
        
        Returns:
            Tuple of (matches, unmatched_old_chunks, unmatched_new_chunks)
        """
        if not old_chunks or not new_chunks:
            return [], old_chunks, new_chunks
        
        matches = []
        matched_old_indices: Set[int] = set()
        matched_new_indices: Set[int] = set()
        
        # Calculate similarity matrix
        similarity_matrix = []
        for old_chunk in old_chunks:
            row = []
            for new_chunk in new_chunks:
                similarity = difflib.SequenceMatcher(
                    None, 
                    old_chunk.text.lower(), 
                    new_chunk.text.lower()
                ).ratio()
                row.append(similarity)
            similarity_matrix.append(row)
        
        # Greedy matching: match highest similarity pairs above threshold
        while True:
            best_match = None
            best_similarity = self.text_similarity_threshold
            best_old_idx = None
            best_new_idx = None
            
            for i, old_chunk in enumerate(old_chunks):
                if i in matched_old_indices:
                    continue
                for j, new_chunk in enumerate(new_chunks):
                    if j in matched_new_indices:
                        continue
                    
                    similarity = similarity_matrix[i][j]
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_old_idx = i
                        best_new_idx = j
                        best_match = (old_chunk, new_chunk)
            
            if best_match is None:
                break
            
            matches.append(ChunkMatch(
                old_chunk=best_match[0],
                new_chunk=best_match[1],
                similarity_score=best_similarity,
                match_type="text"
            ))
            matched_old_indices.add(best_old_idx)
            matched_new_indices.add(best_new_idx)
        
        # Get unmatched chunks
        unmatched_old = [old_chunks[i] for i in range(len(old_chunks)) if i not in matched_old_indices]
        unmatched_new = [new_chunks[i] for i in range(len(new_chunks)) if i not in matched_new_indices]
        
        return matches, unmatched_old, unmatched_new
    
    def _embedding_similarity_match(
        self,
        old_chunks: List[DocumentChunk],
        new_chunks: List[DocumentChunk]
    ) -> Tuple[List[ChunkMatch], List[DocumentChunk], List[DocumentChunk]]:
        """
        Match chunks using embedding-based cosine similarity.
        Slower but more accurate for semantic changes.
        
        Returns:
            Tuple of (matches, unmatched_old_chunks, unmatched_new_chunks)
        """
        if not old_chunks or not new_chunks:
            return [], old_chunks, new_chunks
        
        try:
            # Generate embeddings for all unmatched chunks
            old_texts = [chunk.text for chunk in old_chunks]
            new_texts = [chunk.text for chunk in new_chunks]
            
            old_embeddings = np.array(self.embedding_service.encode_texts(old_texts))
            new_embeddings = np.array(self.embedding_service.encode_texts(new_texts))
            
            # Calculate cosine similarity matrix
            # Normalize embeddings
            old_norms = np.linalg.norm(old_embeddings, axis=1, keepdims=True)
            new_norms = np.linalg.norm(new_embeddings, axis=1, keepdims=True)
            
            # Avoid division by zero
            old_norms = np.where(old_norms == 0, 1, old_norms)
            new_norms = np.where(new_norms == 0, 1, new_norms)
            
            old_normalized = old_embeddings / old_norms
            new_normalized = new_embeddings / new_norms
            
            # Cosine similarity = dot product of normalized vectors
            similarity_matrix = np.dot(old_normalized, new_normalized.T)
            
            # Greedy matching: match highest similarity pairs above threshold
            matches = []
            matched_old_indices: Set[int] = set()
            matched_new_indices: Set[int] = set()
            
            while True:
                best_match = None
                best_similarity = self.similarity_threshold
                best_old_idx = None
                best_new_idx = None
                
                for i in range(len(old_chunks)):
                    if i in matched_old_indices:
                        continue
                    for j in range(len(new_chunks)):
                        if j in matched_new_indices:
                            continue
                        
                        similarity = float(similarity_matrix[i][j])
                        if similarity > best_similarity:
                            best_similarity = similarity
                            best_old_idx = i
                            best_new_idx = j
                            best_match = (old_chunks[i], new_chunks[j])
                
                if best_match is None:
                    break
                
                matches.append(ChunkMatch(
                    old_chunk=best_match[0],
                    new_chunk=best_match[1],
                    similarity_score=best_similarity,
                    match_type="similar"
                ))
                matched_old_indices.add(best_old_idx)
                matched_new_indices.add(best_new_idx)
            
            # Get unmatched chunks
            unmatched_old = [old_chunks[i] for i in range(len(old_chunks)) if i not in matched_old_indices]
            unmatched_new = [new_chunks[i] for i in range(len(new_chunks)) if i not in matched_new_indices]
            
            return matches, unmatched_old, unmatched_new
            
        except Exception as e:
            logger.error(f"Error in embedding similarity matching: {e}")
            # Fallback: return all as unmatched
            return [], old_chunks, new_chunks
    
    def _chunk_hash(self, text: str) -> int:
        """Calculate hash of chunk text for fast comparison"""
        return hash(text.strip().lower())
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors"""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(dot_product / (norm1 * norm2))

