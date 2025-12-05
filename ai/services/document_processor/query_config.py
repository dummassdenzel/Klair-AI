"""
Configuration for query processing and retrieval parameters.
Externalizes all magic numbers and retrieval settings.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class RetrievalConfig:
    """Configuration for retrieval parameters based on query type"""
    
    # Base retrieval parameters
    default_top_k: int = 15
    default_rerank_top_k: int = 15
    default_final_top_k: int = 5
    
    # Listing queries (document inventory)
    listing_top_k: int = 120
    listing_rerank_top_k: int = 0  # No reranking for listing
    listing_final_top_k: int = 120  # Show all
    
    # Comprehensive queries (enumeration-like, but using retrieval)
    comprehensive_top_k: int = 60
    comprehensive_rerank_top_k: int = 30
    comprehensive_final_top_k: int = 20
    
    # Specific file queries
    specific_top_k: int = 30
    specific_rerank_top_k: int = 20
    specific_final_top_k: int = 15
    
    # General queries
    general_top_k: int = 60
    general_rerank_top_k: int = 15
    general_final_top_k: int = 10
    
    # BM25 boost settings
    bm25_boost: float = 0.1
    
    # Source limiting
    max_sources_general: int = 10
    max_sources_specific: int = 20  # No hard limit, but reasonable cap
    
    def get_retrieval_params(self, query_type: str, is_listing: bool = False) -> Dict[str, int]:
        """
        Get retrieval parameters based on query type.
        
        Args:
            query_type: 'greeting', 'general', 'document_listing', or 'document_search'
            is_listing: Whether this is a document listing query
            
        Returns:
            Dict with top_k, rerank_top_k, final_top_k
        """
        if is_listing:
            return {
                'top_k': self.listing_top_k,
                'rerank_top_k': self.listing_rerank_top_k,
                'final_top_k': self.listing_final_top_k
            }
        
        if query_type == 'document_listing':
            return {
                'top_k': self.listing_top_k,
                'rerank_top_k': self.listing_rerank_top_k,
                'final_top_k': self.listing_final_top_k
            }
        
        # For document_search, we'll use comprehensive params for enumeration-like queries
        # This is determined by prompt analysis, not pattern matching
        return {
            'top_k': self.comprehensive_top_k,
            'rerank_top_k': self.comprehensive_rerank_top_k,
            'final_top_k': self.comprehensive_final_top_k
        }
    
    def get_source_limit(self, query_type: str, has_selected_files: bool) -> int:
        """Get maximum number of sources to return"""
        if query_type == 'document_listing':
            return 1000  # No practical limit for listing
        if has_selected_files:
            return self.max_sources_specific
        return self.max_sources_general


# Default configuration instance
default_retrieval_config = RetrievalConfig()

