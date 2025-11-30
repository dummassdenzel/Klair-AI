# Phase 3.3: Priority Queue Manager - Implementation Complete ✅

## Summary

Successfully implemented the Priority Queue Manager for Phase 3: Incremental Updates. This component manages a priority-based queue for document updates, ensuring important files are processed first.

## What Was Implemented

### 1. UpdateTask (`update_queue.py`)

Data class representing an update task:
- `priority`: Priority score (0-1000, higher = more important)
- `file_path`: Path to file to update
- `update_type`: Type of update ("created", "modified", "deleted")
- `strategy`: Update strategy (optional)
- `change_percentage`: Percentage of chunks changed
- `file_size_bytes`: File size
- `enqueued_at`: When task was enqueued
- `last_queried`: When file was last queried
- `is_in_active_session`: Whether in active chat session
- `user_requested`: Whether user explicitly requested update

**Ordering**: Uses dataclass ordering with priority as first field. Higher priority = processed first.

### 2. UpdateResult (`update_queue.py`)

Data class representing update result:
- `success`: Whether update succeeded
- `file_path`: Path to updated file
- `strategy`: Strategy used
- `chunks_updated`: Number of chunks updated
- `processing_time`: Time taken
- `error_message`: Error if failed
- `completed_at`: When completed

### 3. UpdatePriority Enum

Priority levels:
- `LOW = 0`
- `NORMAL = 500`
- `HIGH = 750`
- `URGENT = 1000` (user requested)

### 4. UpdateQueue Class (`update_queue.py`)

Priority queue manager with:

#### Features:
- **Priority-based processing**: Higher priority tasks processed first
- **Active update tracking**: Tracks files currently being processed
- **Completed update history**: Stores last 100 successful updates
- **Failed update tracking**: Stores last 50 failed updates
- **Queue status monitoring**: Real-time queue statistics
- **Duplicate prevention**: Prevents enqueueing same file if already processing

#### Methods:

**`enqueue()`**: Add update to queue
- Calculates priority automatically if not provided
- Prevents duplicates if file already processing
- Returns True if enqueued, False if queue full

**`get_next()`**: Get next task to process
- Blocks until task available or timeout
- Moves task to active updates
- Returns UpdateTask or None

**`mark_completed()`**: Mark update as completed
- Removes from active updates
- Stores in completed/failed history
- Limits history size to prevent memory growth

**`mark_failed()`**: Convenience method to mark as failed

**`get_status()`**: Get queue statistics
- Pending count
- Processing count
- Completed count
- Failed count
- Active file list

**`clear()`**: Clear all pending updates (use with caution)

### 5. Priority Calculation

Automatic priority calculation based on:

1. **User Request** (+1000 points)
   - Explicit "update now" request
   - Always highest priority

2. **Active Session** (+200 points)
   - File is in active chat session
   - User is currently viewing/querying

3. **Recency** (0-400 points)
   - Recently queried files get higher priority
   - Decay: 400 points for < 1 hour, 0 points for > 40 hours
   - Formula: `400 - (hours_since_query * 10)`

4. **File Size** (0-200 points)
   - Smaller files = faster updates = higher priority
   - Formula: `200 - (file_size_mb * 2)`
   - 0 MB = 200 points, 100 MB = 0 points

5. **Change Magnitude** (0-200 points)
   - Smaller changes = faster updates = higher priority
   - Formula: `(1.0 - change_percentage) * 200`
   - 0% change = 200 points, 100% change = 0 points

**Total Range**: 0-1000 points

### 6. Exports (`__init__.py`)

Added to package exports:
- `UpdateQueue`
- `UpdateTask`
- `UpdateResult`
- `UpdatePriority`

### 7. Unit Tests (`test_update_queue.py`)

Comprehensive test suite with 9 test cases:

1. ✅ Enqueue and dequeue operations
2. ✅ Priority ordering (higher priority first)
3. ✅ Priority calculation (all factors)
4. ✅ Active update tracking
5. ✅ Completed update tracking
6. ✅ Queue status reporting
7. ✅ Duplicate prevention
8. ✅ Full queue handling
9. ✅ Timeout behavior

## Usage Example

```python
from services.document_processor import UpdateQueue, UpdateStrategy
from datetime import datetime

# Initialize queue
queue = UpdateQueue(max_queue_size=1000)

# Enqueue update (automatic priority calculation)
await queue.enqueue(
    file_path="document.pdf",
    update_type="modified",
    last_queried=datetime.utcnow() - timedelta(hours=1),
    is_in_active_session=True,
    file_size_bytes=1024*1024,  # 1 MB
    change_percentage=0.1  # 10% changed
)

# Or with explicit priority
await queue.enqueue(
    file_path="urgent.txt",
    priority=UpdatePriority.URGENT,
    user_requested=True
)

# Process updates in a loop
while True:
    task = await queue.get_next(timeout=1.0)
    if task is None:
        continue  # No tasks available
    
    # Process update...
    try:
        # ... do update work ...
        result = UpdateResult(
            success=True,
            file_path=task.file_path,
            strategy=UpdateStrategy.CHUNK_UPDATE,
            chunks_updated=5,
            processing_time=1.5
        )
        await queue.mark_completed(task.file_path, result)
    except Exception as e:
        await queue.mark_failed(task.file_path, str(e))

# Check queue status
status = queue.get_status()
print(f"Pending: {status['pending']}, Processing: {status['processing']}")
```

## Priority Examples

| Scenario | Priority | Reason |
|----------|----------|--------|
| User requested update | 1000 | Urgent |
| Active session, recent, small file, small change | ~900 | High importance |
| Recent query, medium file, medium change | ~500 | Normal |
| Old query, large file, large change | ~100 | Low priority |

## Integration with Phase 3

This component will be used by:

1. **File Monitor** (Phase 3.5)
   - Enqueues updates when files change
   - Uses priority calculation based on file characteristics

2. **Update Executor** (Phase 3.4)
   - Gets tasks from queue
   - Processes updates based on strategy
   - Marks tasks as completed/failed

3. **API Endpoints** (Phase 3.5)
   - Expose queue status to frontend
   - Allow manual priority updates
   - Show update progress

## Dependencies

**No new dependencies!** ✅

Uses only:
- Python built-ins: `asyncio`, `dataclass`, `enum`
- Existing: `UpdateStrategy` from Phase 3.2

## Files Created/Modified

### Created
- `ai/services/document_processor/update_queue.py` (400+ lines)
- `ai/tests/test_update_queue.py` (400+ lines)

### Modified
- `ai/services/document_processor/__init__.py` (added exports)

## Next Steps

Phase 3.3 is complete! Ready to proceed to:

- **Phase 3.4**: Update Executor with Rollback
  - Gets tasks from UpdateQueue
  - Executes updates based on strategy
  - Implements rollback on failure

## Testing

Run tests with:
```bash
cd ai
python tests/test_update_queue.py
```

All 9 tests should pass.

## Notes

- Queue uses `asyncio.PriorityQueue` for thread-safe async operations
- Priority calculation is automatic but can be overridden
- History is limited to prevent memory growth (100 completed, 50 failed)
- Queue doesn't support peeking (asyncio.PriorityQueue limitation)
- Duplicate prevention only checks active updates, not pending queue

