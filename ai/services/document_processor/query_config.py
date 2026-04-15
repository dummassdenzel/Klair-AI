"""
Configuration for query processing and retrieval parameters.
Externalizes all magic numbers and retrieval settings.
"""

import re
from dataclasses import dataclass
from typing import Dict


def is_aggregation_query(question: str) -> bool:
    """
    Heuristic: user is asking for all of a type (total over X, list all X, what are our X).
    For these we need high recall, not just top-k relevance. Domain-agnostic.
    """
    if not question or not question.strip():
        return False
    q = question.strip().lower()
    # "total value of (all) X", "total of all X", "sum of (all) X"
    if re.search(r"total\s+(value\s+)?of\s+(all\s+)?", q) or re.search(r"sum\s+of\s+(all\s+)?", q):
        return True
    # "list all X"
    if re.search(r"list\s+all\s+", q):
        return True
    # "what are our X?", "which X do we have?" — generic: "our" + something (receipts, permits, invoices, documents, etc.)
    if re.search(r"what\s+are\s+our\s+\w+", q) or re.search(r"which\s+(are\s+)?(our\s+)?\w+", q):
        return True
    return False


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
    
    # Comprehensive queries (document_search). T.2: reduced for lower context tokens (~10k → ~3k)
    comprehensive_top_k: int = 40
    comprehensive_rerank_top_k: int = 12
    comprehensive_final_top_k: int = 5
    
    # Aggregation-style ("all X", "total value of X") — higher recall so we don't miss documents
    aggregation_top_k: int = 100
    aggregation_rerank_top_k: int = 60
    aggregation_final_top_k: int = 50
    aggregation_max_sources: int = 50
    
    # Specific file queries
    specific_top_k: int = 30
    specific_rerank_top_k: int = 20
    specific_final_top_k: int = 15
    
    # General queries
    general_top_k: int = 60
    general_rerank_top_k: int = 15
    general_final_top_k: int = 10

    # File-diversity retrieval: max chunks per file in final selection (general search only).
    # Prevents one document from dominating when final_top_k is small (e.g. 5).
    # Specific-document queries (explicit_filename) do not apply this cap.
    max_chunks_per_file: int = 2

    # Source limiting (how many distinct files/sources are passed to the LLM)
    max_sources_general: int = 25   # e.g. "list all delivery notes" — allow more so response can include all relevant files
    max_sources_specific: int = 20  # when user selected specific file(s)
    
    # Per-document cap (chars) when building RAG context so we fit more docs and avoid dropping from tail
    rag_max_per_doc_chars: int = 0  # 0 = no cap for normal queries
    aggregation_max_per_doc_chars: int = 2000  # cap per doc for aggregation so more docs fit in context
    
    def get_retrieval_params(self, query_type: str, is_listing: bool = False, is_aggregation: bool = False) -> Dict[str, int]:
        """
        Get retrieval parameters based on query type.
        
        Args:
            query_type: 'greeting', 'general', 'document_listing', or 'document_search'
            is_listing: Whether this is a document listing query
            is_aggregation: Whether user asked for "all X" / "total value of X" (high recall)
            
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
        
        if is_aggregation:
            return {
                'top_k': self.aggregation_top_k,
                'rerank_top_k': self.aggregation_rerank_top_k,
                'final_top_k': self.aggregation_final_top_k
            }
        
        # For document_search, we'll use comprehensive params for enumeration-like queries
        return {
            'top_k': self.comprehensive_top_k,
            'rerank_top_k': self.comprehensive_rerank_top_k,
            'final_top_k': self.comprehensive_final_top_k
        }

    def get_source_limit(self, query_type: str, has_selected_files: bool, is_aggregation: bool = False) -> int:
        """Get maximum number of sources to return"""
        if query_type == 'document_listing':
            return 1000  # No practical limit for listing
        if is_aggregation:
            return self.aggregation_max_sources
        if has_selected_files:
            return self.max_sources_specific
        return self.max_sources_general
    
    def get_rag_max_per_doc_chars(self, is_aggregation: bool = False) -> int:
        """Max chars per document when building RAG context (0 = no cap). Fits more docs, avoids tail truncation."""
        if is_aggregation and self.aggregation_max_per_doc_chars > 0:
            return self.aggregation_max_per_doc_chars
        return self.rag_max_per_doc_chars


# Default configuration instance
default_retrieval_config = RetrievalConfig()

# Separator used between context chunks when building and parsing retrieved document context.
# Both RetrievalService (joins) and QueryPipelineService (splits) must use the same value.
CONTEXT_CHUNK_SEP = "\n\n---\n\n"

