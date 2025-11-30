"""
Update Strategy Selector

Determines the optimal update strategy based on file characteristics and change analysis.
This helps decide whether to:
- Full re-index (fast for small files or large changes)
- Chunk-level update (efficient for small changes)
- Smart hybrid (balanced approach for medium changes)
"""

import logging
from enum import Enum
from typing import Optional
from dataclasses import dataclass

from .models import ChunkDiffResult

logger = logging.getLogger(__name__)


class UpdateStrategy(Enum):
    """Update strategies for document processing"""
    FULL_REINDEX = "full_reindex"  # Re-process entire document
    CHUNK_UPDATE = "chunk_update"  # Update only changed chunks
    SMART_HYBRID = "smart_hybrid"  # Update changed chunks + verify unchanged


@dataclass
class StrategySelectionResult:
    """Result of strategy selection"""
    strategy: UpdateStrategy
    reason: str  # Explanation of why this strategy was chosen
    estimated_time_savings: Optional[float] = None  # Estimated time savings vs full re-index (0.0-1.0)


class UpdateStrategySelector:
    """
    Selects optimal update strategy based on file characteristics and changes.
    
    Decision factors:
    - Change percentage: How much of the document changed
    - Chunk count: Total number of chunks in the document
    - File size: Size of the file (optional, for future use)
    """
    
    def __init__(
        self,
        full_reindex_threshold: float = 0.5,  # >50% changed → full re-index
        chunk_update_threshold: float = 0.2,  # <20% changed → chunk update
        min_chunks_for_incremental: int = 10,  # Files with <10 chunks always full re-index
        max_chunks_for_full_reindex: int = 1000  # Very large files might benefit from chunk update even with high change %
    ):
        """
        Initialize UpdateStrategySelector
        
        Args:
            full_reindex_threshold: Change percentage above which to use full re-index (default 0.5 = 50%)
            chunk_update_threshold: Change percentage below which to use chunk update (default 0.2 = 20%)
            min_chunks_for_incremental: Minimum chunks needed for incremental updates (default 10)
            max_chunks_for_full_reindex: Maximum chunks where full re-index is always preferred (default 1000)
        """
        self.full_reindex_threshold = full_reindex_threshold
        self.chunk_update_threshold = chunk_update_threshold
        self.min_chunks_for_incremental = min_chunks_for_incremental
        self.max_chunks_for_full_reindex = max_chunks_for_full_reindex
        
        logger.info(
            f"UpdateStrategySelector initialized: "
            f"full_reindex_threshold={full_reindex_threshold}, "
            f"chunk_update_threshold={chunk_update_threshold}, "
            f"min_chunks={min_chunks_for_incremental}"
        )
    
    def select_strategy(
        self,
        diff_result: ChunkDiffResult,
        total_chunks: int,
        file_size_bytes: Optional[int] = None
    ) -> StrategySelectionResult:
        """
        Select optimal update strategy based on change analysis.
        
        Args:
            diff_result: Result from ChunkDiffer comparing old and new chunks
            total_chunks: Total number of chunks in the document
            file_size_bytes: Optional file size in bytes (for future optimizations)
            
        Returns:
            StrategySelectionResult with selected strategy and reasoning
        """
        change_percentage = diff_result.get_change_percentage()
        changed_count = diff_result.get_total_changed_count()
        
        logger.debug(
            f"Selecting strategy: change_pct={change_percentage:.1%}, "
            f"total_chunks={total_chunks}, changed={changed_count}"
        )
        
        # Rule 1: Very small files → always full re-index (overhead not worth it)
        if total_chunks < self.min_chunks_for_incremental:
            reason = (
                f"File has only {total_chunks} chunks (< {self.min_chunks_for_incremental}). "
                f"Full re-index is faster than incremental update overhead."
            )
            logger.debug(reason)
            return StrategySelectionResult(
                strategy=UpdateStrategy.FULL_REINDEX,
                reason=reason,
                estimated_time_savings=0.0
            )
        
        # Rule 2: Large changes → full re-index (most chunks need updating anyway)
        if change_percentage > self.full_reindex_threshold:
            reason = (
                f"Change percentage ({change_percentage:.1%}) exceeds threshold "
                f"({self.full_reindex_threshold:.1%}). Most chunks need updating, "
                f"so full re-index is more efficient."
            )
            logger.debug(reason)
            return StrategySelectionResult(
                strategy=UpdateStrategy.FULL_REINDEX,
                reason=reason,
                estimated_time_savings=0.0
            )
        
        # Rule 3: Small changes → chunk-level update (only update what changed)
        if change_percentage < self.chunk_update_threshold:
            unchanged_count = len(diff_result.unchanged_chunks)
            estimated_savings = unchanged_count / total_chunks if total_chunks > 0 else 0.0
            
            reason = (
                f"Change percentage ({change_percentage:.1%}) is below threshold "
                f"({self.chunk_update_threshold:.1%}). Only {changed_count} chunks changed "
                f"out of {total_chunks}, so chunk-level update is optimal."
            )
            logger.debug(reason)
            return StrategySelectionResult(
                strategy=UpdateStrategy.CHUNK_UPDATE,
                reason=reason,
                estimated_time_savings=estimated_savings
            )
        
        # Rule 4: Medium changes → smart hybrid (update changed, verify unchanged)
        # This is the default case when change percentage is between thresholds
        reason = (
            f"Change percentage ({change_percentage:.1%}) is between thresholds "
            f"({self.chunk_update_threshold:.1%} - {self.full_reindex_threshold:.1%}). "
            f"Using smart hybrid: update {changed_count} changed chunks and verify "
            f"{len(diff_result.unchanged_chunks)} unchanged chunks."
        )
        logger.debug(reason)
        
        # Estimate savings: we still process unchanged chunks but skip embedding generation
        unchanged_count = len(diff_result.unchanged_chunks)
        estimated_savings = 0.3 * (unchanged_count / total_chunks) if total_chunks > 0 else 0.0
        
        return StrategySelectionResult(
            strategy=UpdateStrategy.SMART_HYBRID,
            reason=reason,
            estimated_time_savings=estimated_savings
        )
    
    def select_strategy_simple(
        self,
        change_percentage: float,
        total_chunks: int
    ) -> UpdateStrategy:
        """
        Simplified strategy selection without ChunkDiffResult.
        Useful for quick decisions before running full diff.
        
        Args:
            change_percentage: Percentage of chunks that changed (0.0-1.0)
            total_chunks: Total number of chunks
            
        Returns:
            Selected UpdateStrategy
        """
        if total_chunks < self.min_chunks_for_incremental:
            return UpdateStrategy.FULL_REINDEX
        
        if change_percentage > self.full_reindex_threshold:
            return UpdateStrategy.FULL_REINDEX
        
        if change_percentage < self.chunk_update_threshold:
            return UpdateStrategy.CHUNK_UPDATE
        
        return UpdateStrategy.SMART_HYBRID

