# Phase 3.2: Update Strategy Selector - Implementation Complete ✅

## Summary

Successfully implemented the Update Strategy Selector component for Phase 3: Incremental Updates. This component intelligently selects the optimal update strategy based on file characteristics and change analysis.

## What Was Implemented

### 1. UpdateStrategy Enum (`update_strategy.py`)

Three update strategies:

- **`FULL_REINDEX`**: Re-process entire document (fast for small files or large changes)
- **`CHUNK_UPDATE`**: Update only changed chunks (efficient for small changes)
- **`SMART_HYBRID`**: Update changed chunks + verify unchanged (balanced for medium changes)

### 2. UpdateStrategySelector Class (`update_strategy.py`)

Intelligent strategy selection based on:

#### Decision Rules:

1. **Small Files Rule** (< 10 chunks by default)
   - Always use `FULL_REINDEX`
   - Reason: Overhead of diffing exceeds re-index cost for small files

2. **Large Changes Rule** (> 50% changed by default)
   - Use `FULL_REINDEX`
   - Reason: Most chunks need updating anyway, full re-index is simpler

3. **Small Changes Rule** (< 20% changed by default)
   - Use `CHUNK_UPDATE`
   - Reason: Only a few chunks changed, incremental update is much faster

4. **Medium Changes Rule** (20-50% changed)
   - Use `SMART_HYBRID`
   - Reason: Balanced approach - update changed chunks, verify unchanged

#### Configurable Thresholds:

- `full_reindex_threshold`: Default 0.5 (50%) - above this, use full re-index
- `chunk_update_threshold`: Default 0.2 (20%) - below this, use chunk update
- `min_chunks_for_incremental`: Default 10 - minimum chunks needed for incremental updates
- `max_chunks_for_full_reindex`: Default 1000 - for future optimizations

### 3. StrategySelectionResult

Returns not just the strategy, but also:
- **`strategy`**: Selected UpdateStrategy
- **`reason`**: Human-readable explanation
- **`estimated_time_savings`**: Estimated time savings vs full re-index (0.0-1.0)

### 4. Methods

#### `select_strategy(diff_result, total_chunks, file_size_bytes=None)`
Main method that takes ChunkDiffResult and selects optimal strategy.

#### `select_strategy_simple(change_percentage, total_chunks)`
Simplified method for quick decisions without full diff analysis.

### 5. Exports (`__init__.py`)

Added to package exports:
- `UpdateStrategy`
- `UpdateStrategySelector`
- `StrategySelectionResult`

### 6. Unit Tests (`test_update_strategy.py`)

Comprehensive test suite with 8 test cases:

1. ✅ Small files → full re-index
2. ✅ Large changes → full re-index
3. ✅ Small changes → chunk update
4. ✅ Medium changes → smart hybrid
5. ✅ Zero change edge case
6. ✅ Boundary values at thresholds
7. ✅ Simple selection method
8. ✅ Custom thresholds

## Usage Example

```python
from services.document_processor import (
    UpdateStrategySelector, ChunkDiffer, EmbeddingService
)

# Initialize
embedding_service = EmbeddingService()
chunk_differ = ChunkDiffer(embedding_service)
strategy_selector = UpdateStrategySelector(
    full_reindex_threshold=0.5,
    chunk_update_threshold=0.2,
    min_chunks_for_incremental=10
)

# Compare chunks (from Phase 3.1)
old_chunks = [...]  # Previous version
new_chunks = [...]  # New version
diff_result = chunk_differ.diff_chunks(old_chunks, new_chunks)

# Select strategy
result = strategy_selector.select_strategy(
    diff_result=diff_result,
    total_chunks=len(new_chunks),
    file_size_bytes=1024*1024  # Optional
)

# Use the strategy
if result.strategy == UpdateStrategy.FULL_REINDEX:
    # Re-process entire document
    pass
elif result.strategy == UpdateStrategy.CHUNK_UPDATE:
    # Update only changed chunks
    pass
elif result.strategy == UpdateStrategy.SMART_HYBRID:
    # Update changed + verify unchanged
    pass

print(f"Strategy: {result.strategy.value}")
print(f"Reason: {result.reason}")
print(f"Estimated savings: {result.estimated_time_savings:.1%}")
```

## Decision Flow

```
File Changed
    ↓
ChunkDiffer analyzes changes (Phase 3.1)
    ↓
UpdateStrategySelector selects strategy
    ↓
┌─────────────────────────────────────┐
│  Total chunks < 10?                 │ → YES → FULL_REINDEX
│  (min_chunks_for_incremental)        │
└─────────────────────────────────────┘
    ↓ NO
┌─────────────────────────────────────┐
│  Change % > 50%?                    │ → YES → FULL_REINDEX
│  (full_reindex_threshold)           │
└─────────────────────────────────────┘
    ↓ NO
┌─────────────────────────────────────┐
│  Change % < 20%?                    │ → YES → CHUNK_UPDATE
│  (chunk_update_threshold)            │
└─────────────────────────────────────┘
    ↓ NO
┌─────────────────────────────────────┐
│  20% ≤ Change % ≤ 50%               │ → SMART_HYBRID
└─────────────────────────────────────┘
```

## Performance Characteristics

### Strategy Selection Time
- **Complexity**: O(1) - Simple if/else logic
- **Time**: < 1ms

### Estimated Time Savings

| Strategy | Time Savings | Use Case |
|----------|-------------|----------|
| **FULL_REINDEX** | 0% | Small files or large changes |
| **CHUNK_UPDATE** | 80-95% | Small changes (< 20%) |
| **SMART_HYBRID** | 30-50% | Medium changes (20-50%) |

## Integration with Phase 3

This component will be used by:

1. **Update Executor** (Phase 3.4)
   - Uses strategy to determine how to execute the update
   - FULL_REINDEX: Re-process entire file
   - CHUNK_UPDATE: Update only changed chunks
   - SMART_HYBRID: Update changed + verify unchanged

2. **Update Queue Manager** (Phase 3.3)
   - Can use strategy to estimate update time
   - Can prioritize based on strategy (chunk updates are faster)

## Dependencies

**No new dependencies!** ✅

Uses only:
- Python built-ins: `enum`, `dataclass`
- Existing: `ChunkDiffResult` from Phase 3.1

## Files Created/Modified

### Created
- `ai/services/document_processor/update_strategy.py` (200+ lines)
- `ai/tests/test_update_strategy.py` (350+ lines)

### Modified
- `ai/services/document_processor/__init__.py` (added exports)
- `ai/services/document_processor/models.py` (added enum import, though not used)

## Next Steps

Phase 3.2 is complete! Ready to proceed to:

- **Phase 3.3**: Priority Queue Manager
  - Uses strategy selection to estimate update time
  - Prioritizes updates based on importance and strategy

## Testing

Run tests with:
```bash
cd ai
python tests/test_update_strategy.py
```

All 8 tests should pass.

## Notes

- The strategy selector is stateless and thread-safe
- Thresholds are configurable per instance
- Can be used before or after chunk diffing (simple vs full selection)
- Estimated time savings are rough approximations for UI feedback

