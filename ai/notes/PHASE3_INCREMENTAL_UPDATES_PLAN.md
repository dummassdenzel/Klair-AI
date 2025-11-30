# Phase 3: Incremental Updates - Comprehensive Plan

## Executive Summary

**Current State**: Basic hash-based change detection that triggers full document re-indexing when any change is detected.

**Goal**: Implement intelligent, chunk-level incremental updates that minimize processing time, reduce costs, and improve responsiveness when documents change.

---

## 1. Benefits of Incremental Updates

### 1.1 Performance Benefits

#### **Current Problem**
- **Full Re-indexing**: When a user edits a single paragraph in a 100-page PDF, the entire document is re-processed
- **Wasteful Processing**: Re-extracting text, re-chunking, re-embedding unchanged content
- **High Latency**: Large files take minutes to update, blocking queries

#### **With Incremental Updates**
- **Chunk-Level Updates**: Only changed chunks are re-processed
- **90%+ Time Savings**: For small edits in large files, update time drops from minutes to seconds
- **Non-Blocking**: Updates happen in background, queries remain responsive

**Example Scenario**:
```
File: 50-page contract (500 chunks)
User edits: 1 paragraph (affects 2 chunks)

Current: Re-process entire file = 45 seconds
Phase 3: Update 2 chunks = 2 seconds
Savings: 95% faster
```

### 1.2 Cost Benefits

#### **Current Problem**
- **Unnecessary Embeddings**: Re-generating embeddings for unchanged content
- **LLM Costs**: If using paid embedding APIs, costs scale with full re-indexing
- **Storage Writes**: Deleting and re-inserting all chunks

#### **With Incremental Updates**
- **Selective Embedding**: Only new/changed chunks get embeddings
- **Cost Reduction**: 80-95% reduction in embedding costs for small edits
- **Efficient Storage**: Update-in-place operations instead of delete+insert

**Example Cost Savings**:
```
File: 1000 chunks, user edits 10 chunks
Current: 1000 embeddings × $0.0001 = $0.10
Phase 3: 10 embeddings × $0.0001 = $0.001
Savings: $0.099 (99% reduction)
```

### 1.3 User Experience Benefits

#### **Current Problem**
- **Update Delays**: Users wait for full re-indexing before queries reflect changes
- **Resource Usage**: High CPU/memory during updates, slowing other operations
- **No Progress Feedback**: Users don't know update status

#### **With Incremental Updates**
- **Near-Instant Updates**: Small edits reflected in seconds
- **Background Processing**: Updates don't block queries or UI
- **Progress Tracking**: Users see real-time update status
- **Selective Queries**: Can query updated content immediately, even if other files are updating

### 1.4 Scalability Benefits

#### **Current Problem**
- **Batch Updates**: When multiple files change, each triggers full re-index
- **Resource Contention**: Multiple full re-indexes compete for CPU/memory
- **Queue Backlog**: Updates queue up, delaying critical files

#### **With Incremental Updates**
- **Priority Queue**: Important files (recently queried) update first
- **Parallel Processing**: Multiple small updates can run concurrently
- **Smart Batching**: Group related updates for efficiency
- **Graceful Degradation**: System remains responsive under load

---

## 2. Current Implementation Analysis

### 2.1 What We Have

✅ **Hash-Based Change Detection**
```python
# orchestrator.py:336-340
stored_hash = self.file_hashes.get(file_path)
if not force_reindex and stored_hash == current_hash:
    logger.debug(f"File {file_path} unchanged, skipping re-index")
    return
```

✅ **Full Document Re-indexing**
```python
# orchestrator.py:363-405
# Remove old chunks if re-indexing
if stored_hash and stored_hash != current_hash:
    await self.vector_store.remove_document_chunks(file_path)
    
# Re-process entire document
text = await self.text_extractor.extract_text_async(file_path)
chunks = self.chunker.create_chunks(text, file_path)
embeddings = self.embedding_service.encode_texts([chunk.text for chunk in chunks])
await self.vector_store.batch_insert_chunks(chunks, embeddings)
```

✅ **File Monitor with Debouncing**
```python
# file_monitor.py:136-156
# Debounces rapid file system events
# Prevents duplicate processing
```

✅ **Duplicate Prevention**
```python
# orchestrator.py:325-329
if file_path in self.files_being_processed:
    logger.debug(f"File {file_path} is already being processed, skipping duplicate")
    return
```

### 2.2 What's Missing

❌ **Chunk-Level Diffing**: No way to identify which chunks changed
❌ **Update Strategies**: All files use same update approach
❌ **Priority Queue**: No prioritization of updates
❌ **Rollback Capability**: No way to recover from failed updates
❌ **Progress Tracking**: No visibility into update progress
❌ **Batch Optimization**: No intelligent batching of multiple updates
❌ **Update Scheduling**: No ability to schedule updates during low-usage

---

## 3. Proposed Architecture

### 3.1 Core Components

```
┌─────────────────────────────────────────────────────────────┐
│              Incremental Update System                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────┐    ┌──────────────────┐              │
│  │  Chunk Differ    │    │  Update Strategy │              │
│  │  - Text diff     │    │  - Full re-index │              │
│  │  - Chunk mapping │    │  - Chunk update  │              │
│  │  - Change detect │    │  - Smart hybrid  │              │
│  └──────────────────┘    └──────────────────┘              │
│           │                        │                         │
│           └────────────┬───────────┘                         │
│                        │                                      │
│  ┌──────────────────────────────────────────┐              │
│  │      Update Queue Manager                  │              │
│  │  - Priority queue                          │              │
│  │  - Batch processing                        │              │
│  │  - Progress tracking                       │              │
│  └──────────────────────────────────────────┘              │
│                        │                                      │
│  ┌──────────────────────────────────────────┐              │
│  │      Update Executor                       │              │
│  │  - Chunk-level updates                    │              │
│  │  - Rollback support                       │              │
│  │  - Error handling                         │              │
│  └──────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Chunk Differ Component

**Purpose**: Identify which chunks changed between document versions.

**Approach**:
1. **Text Extraction**: Extract text from old and new versions
2. **Chunk Mapping**: Map old chunks to new chunks using similarity
3. **Change Detection**: Identify added, removed, and modified chunks
4. **Change Classification**: Classify changes (minor edit vs. major rewrite)

**Algorithm**:
```python
class ChunkDiffer:
    def diff_chunks(
        self, 
        old_chunks: List[DocumentChunk], 
        new_chunks: List[DocumentChunk]
    ) -> ChunkDiffResult:
        """
        Returns:
        - unchanged_chunks: List of chunk IDs that didn't change
        - modified_chunks: List of (old_chunk, new_chunk) pairs
        - added_chunks: List of new chunks
        - removed_chunks: List of old chunk IDs to remove
        """
```

**Strategies**:
- **Hash-Based**: Quick check using chunk hashes (fast, but misses semantic changes)
- **Text Similarity**: Use embeddings to find similar chunks (accurate, slower)
- **Hybrid**: Hash first, then similarity for changed regions (balanced)

### 3.3 Update Strategy Selector

**Purpose**: Choose optimal update strategy based on file characteristics.

**Strategies**:

1. **Full Re-index** (Current)
   - When: >50% of chunks changed, or file < 10 chunks
   - Why: Overhead of diffing exceeds re-index cost

2. **Chunk-Level Update** (New)
   - When: <50% of chunks changed, file > 10 chunks
   - Why: Only process changed chunks

3. **Smart Hybrid** (New)
   - When: Medium-sized changes (20-50% of chunks)
   - Why: Update changed chunks, verify unchanged chunks

**Decision Logic**:
```python
def select_strategy(
    file_size: int,
    chunk_count: int,
    changed_chunk_count: int,
    change_percentage: float
) -> UpdateStrategy:
    if change_percentage > 0.5 or chunk_count < 10:
        return UpdateStrategy.FULL_REINDEX
    elif change_percentage < 0.2:
        return UpdateStrategy.CHUNK_UPDATE
    else:
        return UpdateStrategy.SMART_HYBRID
```

### 3.4 Priority Queue Manager

**Purpose**: Prioritize updates based on importance and user activity.

**Priority Factors**:
1. **Recency**: Recently queried files get higher priority
2. **User Activity**: Files in active chat sessions prioritized
3. **File Size**: Smaller files update faster (better throughput)
4. **Change Magnitude**: Small changes process faster
5. **User Request**: Explicit "update now" requests get top priority

**Queue Structure**:
```python
class UpdateQueue:
    def __init__(self):
        self.priority_queue = PriorityQueue()
        self.active_updates = {}  # file_path -> UpdateTask
        self.completed_updates = {}  # file_path -> UpdateResult
    
    def enqueue(
        self, 
        file_path: str, 
        priority: int,
        update_type: str
    ):
        """Add update to priority queue"""
    
    def get_next(self) -> Optional[UpdateTask]:
        """Get next update to process"""
```

**Priority Calculation**:
```python
def calculate_priority(
    file_path: str,
    last_queried: datetime,
    is_in_active_session: bool,
    file_size: int,
    change_percentage: float
) -> int:
    """
    Higher number = higher priority
    Range: 0-1000
    """
    priority = 0
    
    # Recency boost (0-400 points)
    hours_since_query = (now() - last_queried).total_seconds() / 3600
    priority += max(0, 400 - (hours_since_query * 10))
    
    # Active session boost (200 points)
    if is_in_active_session:
        priority += 200
    
    # Size bonus (smaller = faster = higher priority) (0-200 points)
    priority += max(0, 200 - (file_size / 1024 / 1024))  # MB
    
    # Change magnitude bonus (smaller changes = faster) (0-200 points)
    priority += (1 - change_percentage) * 200
    
    return min(1000, int(priority))
```

### 3.5 Update Executor

**Purpose**: Execute updates with rollback support and error handling.

**Features**:
- **Atomic Operations**: Updates succeed or fail completely
- **Rollback**: Restore previous state on failure
- **Progress Tracking**: Report progress for UI
- **Error Recovery**: Retry failed updates with exponential backoff

**Implementation**:
```python
class UpdateExecutor:
    async def execute_update(
        self, 
        update_task: UpdateTask
    ) -> UpdateResult:
        """
        Execute update with rollback support
        """
        # 1. Create checkpoint (save current state)
        checkpoint = await self._create_checkpoint(update_task.file_path)
        
        try:
            # 2. Execute update based on strategy
            if update_task.strategy == UpdateStrategy.CHUNK_UPDATE:
                result = await self._execute_chunk_update(update_task)
            else:
                result = await self._execute_full_reindex(update_task)
            
            # 3. Verify update success
            await self._verify_update(update_task.file_path)
            
            return UpdateResult(success=True, ...)
            
        except Exception as e:
            # 4. Rollback on failure
            await self._rollback(checkpoint)
            return UpdateResult(success=False, error=str(e))
```

---

## 4. Impact on Application Flow

### 4.1 Current Flow (Before Phase 3)

```
User edits file
    ↓
File Monitor detects change
    ↓
Debounce delay (2 seconds)
    ↓
add_document() called
    ↓
Hash check → File changed
    ↓
Remove ALL old chunks
    ↓
Extract ALL text
    ↓
Create ALL chunks
    ↓
Generate ALL embeddings
    ↓
Insert ALL chunks
    ↓
Update database
    ↓
Done (45 seconds for large file)
```

### 4.2 New Flow (After Phase 3)

```
User edits file
    ↓
File Monitor detects change
    ↓
Debounce delay (2 seconds)
    ↓
Update Queue enqueues with priority
    ↓
Chunk Differ analyzes changes
    ↓
Update Strategy selected
    ↓
[If Chunk Update Strategy]
    ↓
Identify changed chunks only
    ↓
Remove only changed chunks
    ↓
Extract text for changed regions
    ↓
Create only new/modified chunks
    ↓
Generate embeddings for changed chunks only
    ↓
Update chunks in-place
    ↓
Update database
    ↓
Done (2-5 seconds for small edit)
```

### 4.3 Query Flow Impact

**Before Phase 3**:
- Queries may return stale results during long updates
- Large updates block query processing
- No way to query partially updated files

**After Phase 3**:
- Queries return latest available data (even if update in progress)
- Updates don't block queries (background processing)
- Can query updated chunks immediately, even if other chunks updating

---

## 5. Implementation Plan

### 5.1 Phase 3.1: Chunk Differ (Foundation)

**Goal**: Build core chunk diffing capability

**Tasks**:
1. Create `ChunkDiffer` class
2. Implement hash-based chunk matching
3. Implement text similarity matching (using existing embeddings)
4. Add chunk mapping algorithm
5. Create `ChunkDiffResult` data structure
6. Unit tests for chunk diffing

**Files to Create**:
- `ai/services/document_processor/chunk_differ.py`

**Files to Modify**:
- `ai/services/document_processor/orchestrator.py` (integrate ChunkDiffer)

**Estimated Time**: 2-3 days

### 5.2 Phase 3.2: Update Strategy Selector

**Goal**: Implement intelligent strategy selection

**Tasks**:
1. Create `UpdateStrategy` enum
2. Create `UpdateStrategySelector` class
3. Implement decision logic
4. Add configuration for thresholds
5. Unit tests for strategy selection

**Files to Create**:
- `ai/services/document_processor/update_strategy.py`

**Files to Modify**:
- `ai/services/document_processor/orchestrator.py` (use strategy selector)

**Estimated Time**: 1 day

### 5.3 Phase 3.3: Priority Queue Manager

**Goal**: Implement prioritized update queue

**Tasks**:
1. Create `UpdateQueue` class with priority queue
2. Implement priority calculation
3. Add queue management (enqueue, dequeue, status)
4. Integrate with file monitor
5. Add queue status API endpoint
6. Unit tests for queue management

**Files to Create**:
- `ai/services/document_processor/update_queue.py`

**Files to Modify**:
- `ai/services/file_monitor.py` (enqueue instead of direct call)
- `ai/services/document_processor/orchestrator.py` (process from queue)
- `ai/main.py` (add queue status endpoint)

**Estimated Time**: 2 days

### 5.4 Phase 3.4: Update Executor with Rollback

**Goal**: Execute updates with safety and rollback

**Tasks**:
1. Create `UpdateExecutor` class
2. Implement checkpoint creation
3. Implement chunk-level update execution
4. Implement rollback mechanism
5. Add progress tracking
6. Add error recovery/retry logic
7. Integration tests

**Files to Create**:
- `ai/services/document_processor/update_executor.py`

**Files to Modify**:
- `ai/services/document_processor/orchestrator.py` (use executor)
- `ai/services/document_processor/vector_store.py` (add update-in-place methods)

**Estimated Time**: 3-4 days

### 5.5 Phase 3.5: Integration & Frontend

**Goal**: Integrate all components and add UI feedback

**Tasks**:
1. Integrate all Phase 3 components
2. Add update status tracking in database
3. Create API endpoints for update status
4. Add frontend UI for update progress
5. Add update history/logs
6. End-to-end testing

**Files to Modify**:
- `ai/database/models.py` (add update tracking fields)
- `ai/main.py` (add update status endpoints)
- `src/lib/components/Sidebar.svelte` (show update status)
- `src/routes/+page.svelte` (show update notifications)

**Estimated Time**: 2-3 days

---

## 6. Database Schema Changes

### 6.1 New Table: `document_updates`

```python
class DocumentUpdate(Base):
    __tablename__ = "document_updates"
    
    id = Column(Integer, primary_key=True)
    file_path = Column(String, ForeignKey("indexed_documents.file_path"))
    update_type = Column(String)  # "full_reindex", "chunk_update", "smart_hybrid"
    status = Column(String)  # "pending", "processing", "completed", "failed"
    priority = Column(Integer)
    chunks_changed = Column(Integer)  # Number of chunks that changed
    chunks_total = Column(Integer)  # Total chunks in file
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    rollback_checkpoint = Column(Text)  # JSON of checkpoint data
```

### 6.2 Modify: `IndexedDocument`

```python
# Add fields to IndexedDocument
last_update_type = Column(String)  # Last update strategy used
last_update_at = Column(DateTime)
update_in_progress = Column(Boolean, default=False)
```

---

## 7. API Endpoints

### 7.1 New Endpoints

```python
# Get update queue status
GET /api/updates/queue
Response: {
    "pending": 5,
    "processing": 2,
    "completed_today": 10,
    "queue": [
        {
            "file_path": "...",
            "priority": 850,
            "status": "pending",
            "enqueued_at": "..."
        }
    ]
}

# Get update status for a file
GET /api/updates/status/{file_path}
Response: {
    "status": "processing",
    "progress": 0.65,  # 65% complete
    "chunks_updated": 13,
    "chunks_total": 20,
    "started_at": "...",
    "estimated_completion": "..."
}

# Force update a file
POST /api/updates/force
Body: {"file_path": "..."}
Response: {
    "status": "enqueued",
    "priority": 1000,
    "estimated_start": "..."
}
```

---

## 8. Performance Metrics

### 8.1 Key Metrics to Track

1. **Update Time**
   - Average update time (before vs. after)
   - Update time by file size
   - Update time by change percentage

2. **Cost Savings**
   - Embeddings generated (before vs. after)
   - API costs (if using paid embeddings)

3. **User Experience**
   - Time to reflect changes in queries
   - Update queue wait time
   - Failed update rate

4. **System Performance**
   - CPU usage during updates
   - Memory usage
   - Concurrent update capacity

### 8.2 Expected Improvements

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Small edit (1% change) | 45s | 2s | **95% faster** |
| Medium edit (20% change) | 45s | 10s | **78% faster** |
| Large edit (80% change) | 45s | 40s | **11% faster** |
| Embeddings (small edit) | 500 | 5 | **99% reduction** |
| Query latency (during update) | Blocked | <100ms | **Non-blocking** |

---

## 9. Risks & Mitigations

### 9.1 Risk: Chunk Mapping Complexity

**Risk**: Accurately mapping old chunks to new chunks is complex, especially with major edits.

**Mitigation**:
- Start with hash-based matching (simple, fast)
- Fall back to full re-index if mapping confidence is low
- Use hybrid approach: hash for unchanged, similarity for changed

### 9.2 Risk: Rollback Complexity

**Risk**: Rollback mechanism adds complexity and potential bugs.

**Mitigation**:
- Start simple: checkpoint = save old chunks before update
- Test rollback extensively
- Have fallback to full re-index if rollback fails

### 9.3 Risk: Performance Overhead

**Risk**: Diffing and strategy selection add overhead that might negate benefits.

**Mitigation**:
- Benchmark diffing time vs. re-index time
- Use fast diffing (hash-based) first, only use similarity for changed regions
- Skip diffing for very small files (< 10 chunks)

### 9.4 Risk: Data Consistency

**Risk**: Partial updates might leave inconsistent state.

**Mitigation**:
- Use transactions where possible
- Verify updates after completion
- Have rollback mechanism
- Add integrity checks

---

## 10. Testing Strategy

### 10.1 Unit Tests

- ChunkDiffer: Test diffing with various change scenarios
- UpdateStrategySelector: Test strategy selection logic
- UpdateQueue: Test priority queue behavior
- UpdateExecutor: Test update execution and rollback

### 10.2 Integration Tests

- End-to-end update flow with real files
- Multiple concurrent updates
- Update failure and rollback scenarios
- Query during update scenarios

### 10.3 Performance Tests

- Benchmark update times (before vs. after)
- Measure cost savings (embeddings generated)
- Test system under load (many updates)

### 10.4 Manual Testing

- Edit small portion of large file → verify fast update
- Edit large portion → verify appropriate strategy
- Multiple file edits → verify queue prioritization
- Update failure → verify rollback

---

## 11. Success Criteria

✅ **Performance**: 80%+ reduction in update time for small edits (<20% change)
✅ **Cost**: 80%+ reduction in embeddings generated for small edits
✅ **UX**: Updates complete in <5 seconds for small edits
✅ **Reliability**: <1% update failure rate with successful rollback
✅ **Scalability**: Handle 10+ concurrent updates without degradation

---

## 12. Future Enhancements (Post-Phase 3)

- **Incremental Chunking**: Only re-chunk changed regions
- **Semantic Diffing**: Detect semantic changes even if text unchanged
- **Update Scheduling**: Schedule updates during low-usage periods
- **Predictive Updates**: Pre-update files likely to be queried soon
- **Distributed Updates**: Scale updates across multiple workers

---

## Summary

Phase 3: Incremental Updates transforms our document processing from a "full re-index on any change" model to an intelligent, chunk-level update system. This provides:

- **95% faster updates** for small edits
- **99% cost reduction** for embedding generation
- **Non-blocking queries** during updates
- **Better user experience** with near-instant change reflection
- **Production-ready scalability** for handling many concurrent updates

The implementation is broken into 5 sub-phases, each building on the previous, allowing for incremental delivery and testing.

