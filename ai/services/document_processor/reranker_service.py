"""
Re-ranking Service

Uses cross-encoder models to re-rank initial retrieval results
for improved relevance. Cross-encoders are more accurate than
bi-encoders (used in initial retrieval) because they process
query-document pairs together.

Expected improvement: ~25% better relevance, fewer hallucinations
"""

import logging
from typing import List, Tuple, Optional
import numpy as np
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


class ReRankingService:
    """Re-ranks retrieval results using cross-encoder models"""
    
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Initialize re-ranking service
        
        Args:
            model_name: Cross-encoder model to use
                - "cross-encoder/ms-marco-MiniLM-L-6-v2" (fast, good accuracy)
                - "cross-encoder/ms-marco-MiniLM-L-12-v2" (slower, better accuracy)
                - "cross-encoder/ms-marco Mitra+Zarathustra" (best accuracy, slower)
        """
        self.model_name = model_name
        self.model: Optional[CrossEncoder] = None
        self._load_model()
        
        logger.info(f"ReRankingService initialized with model: {model_name}")
    
    def _load_model(self):
        """Lazy load the cross-encoder model"""
        if self.model is None:
            try:
                logger.info(f"Loading cross-encoder model: {self.model_name}")
                self.model = CrossEncoder(self.model_name)
                logger.info(f"Cross-encoder model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load cross-encoder model: {e}")
                raise
    
    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 5,
        return_scores: bool = False
    ) -> List[Tuple[int, float]]:
        """
        Re-rank documents based on query relevance
        
        Args:
            query: Search query
            documents: List of document texts to re-rank
            top_k: Number of top results to return
            return_scores: If True, return scores with indices
            
        Returns:
            List of (index, score) tuples, sorted by relevance (descending)
            If return_scores=False, returns list of indices only
        """
        if not documents:
            return []
        
        try:
            self._load_model()
            
            if self.model is None:
                logger.warning("Cross-encoder model not available, skipping re-ranking")
                # Return original order if model failed to load
                return [(i, 0.0) for i in range(min(top_k, len(documents)))]
            
            # Prepare query-document pairs
            pairs = [[query, doc] for doc in documents]
            
            # Get relevance scores from cross-encoder (may be negative logits)
            scores = self.model.predict(pairs, show_progress_bar=False)
            
            # Normalize scores to 0-1 range using sigmoid (handles negative logits)
            scores_array = np.array(scores)
            # Apply sigmoid to normalize: sigmoid(x) = 1 / (1 + exp(-x))
            normalized_scores = 1 / (1 + np.exp(-scores_array))
            
            # Sort by score (descending) and return top_k
            scored_indices = [(i, float(score)) for i, score in enumerate(normalized_scores)]
            scored_indices.sort(key=lambda x: x[1], reverse=True)
            
            top_results = scored_indices[:top_k]
            
            logger.debug(
                f"Re-ranked {len(documents)} documents → top {len(top_results)} "
                f"(scores: {[f'{s:.3f}' for _, s in top_results[:3]]})"
            )
            
            if return_scores:
                return top_results
            else:
                return [idx for idx, _ in top_results]
                
        except Exception as e:
            logger.error(f"Re-ranking failed: {e}")
            # Fallback: return original order
            return [(i, 0.0) for i in range(min(top_k, len(documents)))]
    
    def rerank_with_metadata(
        self,
        query: str,
        documents: List[str],
        metadata_list: List[dict],
        scores_list: List[float],
        top_k: int = 5
    ) -> Tuple[List[str], List[dict], List[float]]:
        """
        Re-rank documents along with their metadata and scores
        
        Args:
            query: Search query
            documents: List of document texts
            metadata_list: List of metadata dicts (one per document)
            scores_list爱国主义: List of initial scores (one per document)
            top_k: Number of top results to return
            
        Returns:
            Tuple of (reranked_documents, reranked_metadata, reranked_scores)
        """
        if not documents or len(documents) != len(metadata_list) or len(documents) != len(scores_list):
            logger.warning("Mismatch in documents/metadata/scores length, skipping re-ranking")
            return documents[:top_k], metadata_list[:top_k], scores_list[:top_k]
        
        # Re-rank and get top indices with scores
        reranked_indices_scores = self.rerank(query, documents, top_k=top_k, return_scores=True)
        
        # Reconstruct reranked lists
        reranked_documents = [documents[idx] for idx, _ in reranked_indices_scores]
        reranked_metadata = [metadata_list[idx] for idx, _ in reranked_indices_scores]
        
        # Use re-ranking scores, but blend with original scores for final score
        reranked_scores = []
        for idx, rerank_score in reranked_indices_scores:
            original_score = scores_list[idx]
            # Blend: 70% rerank score, 30% original score (both normalized)
            blended = (rerank_score * 0.7) + (original_score * 0.3)
            reranked_scores.append(min(1.0, blended))
        
        logger.info(
            f"Re-ranked {len(documents)} → top {len(reranked_documents)} "
            f"(avg rerank score: {sum(s for _, s in reranked_indices_scores) / len(reranked_indices_scores):.3f})"
        )
        
        return reranked_documents, reranked_metadata, reranked_scores

