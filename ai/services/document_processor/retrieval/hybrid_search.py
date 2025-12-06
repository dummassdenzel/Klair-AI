"""
Hybrid Search Service

Combines semantic search (ChromaDB) and keyword search (BM25) using
Reciprocal Rank Fusion (RRF) for optimal retrieval quality.

This approach is used by:
- Perplexity AI
- You.com
- Enterprise RAG systems (AWS Kendra, etc.)
"""

import logging
from typing import List, Dict, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class HybridSearchService:
    """Combines multiple search methods using Reciprocal Rank Fusion"""
    
    def __init__(self, k: int = 60):
        """
        Initialize hybrid search service
        
        Args:
            k: RRF constant (default 60 is standard in literature)
               Higher k = more weight to lower ranks
        """
        self.k = k
        logger.info(f"HybridSearchService initialized (RRF k={k})")
    
    def fuse_results(
        self,
        semantic_results: List[Tuple[str, float, Dict]],
        keyword_results: List[Tuple[str, float, Dict]],
        semantic_weight: float = 0.5,
        keyword_weight: float = 0.5
    ) -> List[Tuple[str, float, Dict]]:
        """
        Combine semantic and keyword search results using Reciprocal Rank Fusion (RRF)
        
        RRF Formula: score(d) = Σ 1 / (k + rank(d))
        
        Args:
            semantic_results: List of (id, score, metadata) from semantic search
            keyword_results: List of (id, score, metadata) from keyword search
            semantic_weight: Weight for semantic search (0-1)
            keyword_weight: Weight for keyword search (0-1)
            
        Returns:
            Fused results as List of (id, fused_score, metadata), sorted by score
        """
        # Normalize weights
        total_weight = semantic_weight + keyword_weight
        semantic_weight = semantic_weight / total_weight
        keyword_weight = keyword_weight / total_weight
        
        # Calculate RRF scores
        rrf_scores = defaultdict(float)
        doc_metadata = {}  # Store metadata for each doc
        
        # Process semantic results
        for rank, (doc_id, score, metadata) in enumerate(semantic_results, start=1):
            rrf_scores[doc_id] += semantic_weight * (1.0 / (self.k + rank))
            if doc_id not in doc_metadata:
                doc_metadata[doc_id] = metadata
        
        # Process keyword results
        for rank, (doc_id, score, metadata) in enumerate(keyword_results, start=1):
            rrf_scores[doc_id] += keyword_weight * (1.0 / (self.k + rank))
            if doc_id not in doc_metadata:
                doc_metadata[doc_id] = metadata
        
        # Sort by fused score (descending)
        fused_results = [
            (doc_id, score, doc_metadata[doc_id])
            for doc_id, score in sorted(
                rrf_scores.items(),
                key=lambda x: x[1],
                reverse=True
            )
        ]
        
        logger.debug(
            f"Fused {len(semantic_results)} semantic + {len(keyword_results)} keyword "
            f"results → {len(fused_results)} unique documents"
        )
        
        return fused_results
    
    def analyze_fusion(
        self,
        semantic_results: List[Tuple[str, float, Dict]],
        keyword_results: List[Tuple[str, float, Dict]],
        fused_results: List[Tuple[str, float, Dict]],
        top_k: int = 5
    ) -> Dict:
        """
        Analyze how fusion affected rankings (for debugging/optimization)
        
        Returns:
            Dict with fusion statistics
        """
        semantic_ids = {doc_id for doc_id, _, _ in semantic_results[:top_k]}
        keyword_ids = {doc_id for doc_id, _, _ in keyword_results[:top_k]}
        fused_ids = {doc_id for doc_id, _, _ in fused_results[:top_k]}
        
        # Calculate overlap
        semantic_only = semantic_ids - keyword_ids
        keyword_only = keyword_ids - semantic_ids
        both = semantic_ids & keyword_ids
        
        # Calculate agreement with fused top-k
        semantic_in_fused = len(semantic_ids & fused_ids)
        keyword_in_fused = len(keyword_ids & fused_ids)
        
        return {
            "semantic_count": len(semantic_results),
            "keyword_count": len(keyword_results),
            "fused_count": len(fused_results),
            "top_k": top_k,
            "overlap": {
                "both_methods": len(both),
                "semantic_only": len(semantic_only),
                "keyword_only": len(keyword_only)
            },
            "agreement_with_fused": {
                "semantic": semantic_in_fused,
                "keyword": keyword_in_fused
            }
        }

