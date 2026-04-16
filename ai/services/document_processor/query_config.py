"""
Configuration for query processing and retrieval parameters.
Externalizes all magic numbers and retrieval settings.
"""

import re
from dataclasses import dataclass
from typing import Dict


def is_aggregation_query(question: str) -> bool:
    """
    Heuristic: detect queries that require exhaustive high-recall retrieval — i.e. the user
    wants a total, combined value, or enumeration across ALL matching documents, not just the
    most relevant one.

    Only fires on explicit numerical/exhaustive-intent signals.  Broad patterns like
    "what are our X" or "which X" were deliberately removed because they fired on ordinary
    questions ("what are our options?", "which file?") and sent them down the expensive
    aggregation path (top_k=100) with no benefit.
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
    # "total/combined/aggregate/overall value/amount/cost/sum [of X]"
    if re.search(r"(total|combined|aggregate|overall)\s+(value|amount|cost|sum)", q):
        return True
    # "add up all X", "add together all X"
    if re.search(r"add\s+(up|together)\s+all", q):
        return True
    return False


@dataclass
class RetrievalConfig:
    """Configuration for retrieval parameters based on query type"""
    
    # Base retrieval parameters
    default_top_k: int = 15
    default_final_top_k: int = 5

    # Listing queries (document inventory)
    listing_top_k: int = 120
    listing_final_top_k: int = 120  # Show all

    # Comprehensive queries (standard document_search).
    # Retrieve 40 candidates via hybrid RRF, then pass the top 12 to the LLM.
    # 12 chunks × 300 tokens ≈ 3,600 tokens of context — ~29% of Groq's 128k window.
    # Previously 5 chunks (~12% utilization); raised to 12 so multi-section documents
    # (e.g. a delivery receipt spanning 6+ chunks) are adequately covered.
    comprehensive_top_k: int = 40
    comprehensive_final_top_k: int = 12

    # Aggregation-style ("all X", "total value of X") — higher recall so we don't miss documents
    aggregation_top_k: int = 100
    aggregation_final_top_k: int = 50
    aggregation_max_sources: int = 50

    # Specific file queries
    specific_top_k: int = 30
    specific_final_top_k: int = 15

    # General queries
    general_top_k: int = 60
    general_final_top_k: int = 10

    # File-diversity retrieval: max chunks per file in the final selection window.
    # Prevents one document from consuming all slots when many files are relevant.
    # Specific-document queries (explicit_filename) bypass this cap entirely.
    # Raised from 2 → 4: with 300-token chunks a single document (e.g. a delivery
    # receipt with a header, line-item table, and total section) often spans 6–8 chunks;
    # a cap of 2 was silently dropping the most informative middle/tail chunks.
    max_chunks_per_file: int = 4

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
            Dict with top_k, final_top_k
        """
        if is_listing or query_type == 'document_listing':
            return {
                'top_k': self.listing_top_k,
                'final_top_k': self.listing_final_top_k,
            }

        if is_aggregation:
            return {
                'top_k': self.aggregation_top_k,
                'final_top_k': self.aggregation_final_top_k,
            }

        # Comprehensive (document_search)
        return {
            'top_k': self.comprehensive_top_k,
            'final_top_k': self.comprehensive_final_top_k,
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

