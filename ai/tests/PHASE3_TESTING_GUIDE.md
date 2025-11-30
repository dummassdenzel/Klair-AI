# Phase 3.5 Integration Testing Guide

This guide provides comprehensive testing steps to verify Phase 3.5 integration works correctly.

## Prerequisites

1. **Activate virtual environment:**
   ```bash
   cd ai
   # On Windows:
   .venv\Scripts\activate
   # On Linux/Mac:
   source .venv/bin/activate
   ```

2. **Ensure dependencies are installed:**
   ```bash
   pip install -r requirements.txt
   ```

## Automated Tests

### 1. Quick Import Test

Test that all Phase 3 components can be imported:

```bash
cd ai
python tests/quick_test_phase3.py
```

**Expected Output:**
```
✅ All Phase 3 components imported
✅ FileMonitorService imported
✅ Orchestrator initialized with all Phase 3 components
✅ enqueue_update method available
✅ UpdateQueue status method works
✅ ALL TESTS PASSED!
```

### 2. Full Integration Test

Run the comprehensive integration test:

```bash
cd ai
python tests/test_phase3_integration.py
```

**Expected Output:**
- All 6 tests should pass
- No import errors
- No initialization errors

### 3. Individual Component Tests

Test each Phase 3 component individually:

```bash
cd ai
python tests/test_chunk_differ.py
python tests/test_update_strategy.py
python tests/test_update_queue.py
python tests/test_update_executor.py
```

**Expected:** All tests pass

## Manual Testing Steps

### Step 1: Start the Backend Server

```bash
cd ai
python main.py
```

**Check for:**
- ✅ Server starts without errors
- ✅ No import errors in logs
- ✅ "Update worker started" message appears in logs

### Step 2: Verify API Endpoints

Test the new API endpoints using curl or Postman:

#### 2.1 Get Update Queue Status
```bash
curl http://localhost:8000/api/updates/queue
```

**Expected Response:**
```json
{
  "status": "success",
  "queue": {
    "pending": 0,
    "processing": 0,
    "completed": 0,
    "failed": 0,
    "pending_tasks": []
  }
}
```

#### 2.2 Force Update a File
```bash
curl -X POST http://localhost:8000/api/updates/force \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/test/file.txt"}'
```

**Expected Response:**
```json
{
  "status": "success",
  "message": "Update enqueued for /path/to/test/file.txt with high priority"
}
```

### Step 3: Test File Monitoring Integration

1. **Start the server** (if not already running)

2. **Set a directory** via the frontend or API:
   ```bash
   curl -X POST http://localhost:8000/api/set-directory \
     -H "Content-Type: application/json" \
     -d '{"path": "/path/to/test/directory"}'
   ```

3. **Create or modify a file** in the monitored directory

4. **Check logs** for:
   - ✅ "Enqueued modified for /path/to/file" message
   - ✅ Update worker processing the file
   - ✅ Update completed successfully

5. **Check queue status:**
   ```bash
   curl http://localhost:8000/api/updates/queue
   ```
   
   **Expected:** Queue should show processing or completed updates

### Step 4: Test Frontend Integration

1. **Start the frontend:**
   ```bash
   cd src
   npm run dev
   ```

2. **Open browser** to `http://localhost:5173`

3. **Select a directory** via the directory picker

4. **Verify:**
   - ✅ Metadata indexing completes quickly
   - ✅ Content indexing happens in background
   - ✅ Update queue status appears in sidebar (if updates are pending)
   - ✅ "Updating" badge appears when files are being updated

5. **Modify a file** in the selected directory

6. **Verify:**
   - ✅ Update queue status updates in real-time
   - ✅ File gets updated without full re-index
   - ✅ Changes are reflected in search results

### Step 5: Test Incremental Updates

1. **Index a document** (via initial indexing)

2. **Modify the document** (add/remove/edit content)

3. **Check logs** for:
   - ✅ ChunkDiffer analyzing changes
   - ✅ UpdateStrategySelector choosing strategy
   - ✅ UpdateExecutor processing only changed chunks
   - ✅ Processing time is faster than full re-index

4. **Verify in database:**
   - ✅ Only modified chunks are updated
   - ✅ Unchanged chunks remain the same
   - ✅ File hash is updated

## Common Issues and Solutions

### Issue: Import Errors

**Symptom:** `ModuleNotFoundError` or `ImportError`

**Solution:**
1. Ensure virtual environment is activated
2. Install dependencies: `pip install -r requirements.txt`
3. Check Python path includes `ai` directory

### Issue: Update Worker Not Starting

**Symptom:** No "Update worker started" message in logs

**Solution:**
1. Check orchestrator initialization logs
2. Verify `update_worker.start()` is called
3. Check for async task errors

### Issue: Queue Not Processing

**Symptom:** Updates stay in "pending" status

**Solution:**
1. Check if update worker is running: `orchestrator.update_worker.is_running`
2. Check logs for worker errors
3. Verify file paths are valid

### Issue: Frontend Not Showing Updates

**Symptom:** Update queue status not updating in UI

**Solution:**
1. Check browser console for API errors
2. Verify polling is active (check Network tab)
3. Check `updateQueueStatus` store is being updated

## Verification Checklist

- [ ] All imports work without errors
- [ ] Orchestrator initializes with Phase 3 components
- [ ] Update worker starts automatically
- [ ] `enqueue_update()` method works
- [ ] FileMonitor uses update queue
- [ ] API endpoints return correct data
- [ ] Frontend displays update status
- [ ] Incremental updates process faster than full re-index
- [ ] Failed updates roll back correctly
- [ ] Queue prioritizes important files

## Performance Benchmarks

After testing, verify:

1. **Small file update (< 10 chunks):**
   - Should complete in < 5 seconds
   - Only changed chunks processed

2. **Medium file update (10-100 chunks):**
   - Should complete in < 30 seconds
   - Chunk-level updates used

3. **Large file update (> 100 chunks):**
   - Strategy selector chooses appropriate method
   - Processing time reasonable

## Next Steps

If all tests pass:
1. ✅ Phase 3.5 integration is complete
2. ✅ System is ready for production use
3. ✅ Monitor logs for any edge cases

If tests fail:
1. Review error messages
2. Check component integration points
3. Verify all dependencies are installed
4. Check database connectivity

