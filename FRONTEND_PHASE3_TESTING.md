# Frontend Phase 3.5 Testing Guide

This guide helps you verify that all Phase 3.5 features are working correctly in the frontend.

## Prerequisites

1. **Backend server is running:**
   ```bash
   cd ai
   python main.py
   ```
   - Should see "Update worker started" in logs
   - Server should be running on `http://localhost:8000`

2. **Frontend dependencies installed:**
   ```bash
   cd src
   npm install
   ```

## Step 1: Start the Frontend

```bash
cd src
npm run dev
```

Frontend should start on `http://localhost:5173` (or similar port).

## Step 2: Initial Setup Test

1. **Open browser** to `http://localhost:5173`

2. **Select a directory** via the directory picker

3. **Verify:**
   - ✅ Directory selection modal appears
   - ✅ After selection, metadata indexing starts
   - ✅ "Indexing document metadata..." message appears
   - ✅ Files appear in sidebar quickly (metadata-first indexing)

## Step 3: Check Update Queue Status Display

### 3.1 Visual Check

1. **Open browser DevTools** (F12)

2. **Go to Console tab** - Check for errors

3. **Check Sidebar:**
   - Open the documents view in sidebar
   - Look for "Updating" badge next to "Indexed Documents" header
   - Badge should appear when updates are pending/processing

### 3.2 SSE Stream Check

1. **Open Network tab** in DevTools

2. **Filter by "stream"** or look for requests to `/api/updates/stream`

3. **Verify:**
   - ✅ SSE connection is established (EventStream type)
   - ✅ Connection stays open (persistent connection)
   - ✅ Events are received when status changes
   - ✅ No polling requests (no repeated GET requests)
     ```json
     {
       "status": "success",
       "queue": {
         "pending": 0,
         "processing": 0,
         "completed": 0,
         "failed": 0
       }
     }
     ```

### 3.3 Console Check

In browser console, check for:
- ✅ No errors related to `updateQueueStatus`
- ✅ No errors about SSE connection
- ✅ SSE connection established message
- ✅ No polling requests (SSE is push-based, not polling)

## Step 4: Test File Modification Trigger

### 4.1 Modify a File

1. **Select a directory** with some documents

2. **Wait for initial indexing** to complete

3. **Modify a file** in the selected directory:
   - Open a `.txt`, `.docx`, or `.pdf` file
   - Make a small change (add/remove text)
   - Save the file

### 4.2 Verify Update Queue

1. **Check backend logs:**
   - Should see: `"Enqueued modified for /path/to/file"`
   - Should see: `"Processing update task for /path/to/file"`

2. **Check frontend:**
   - **Sidebar**: "Updating" badge should appear
   - **Network tab**: Queue status should show `pending > 0` or `processing > 0`
   - **Console**: No errors

3. **Wait for update to complete:**
   - Badge should disappear when update completes
   - Queue status should return to normal

## Step 5: Test Force Update API

### 5.1 Using Browser Console

1. **Open browser console** (F12)

2. **Test the API directly:**
   ```javascript
   // Get queue status
   fetch('http://localhost:8000/api/updates/queue')
     .then(r => r.json())
     .then(console.log);

   // Force update a file
   fetch('http://localhost:8000/api/updates/force', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ file_path: '/path/to/your/file.txt' })
   })
     .then(r => r.json())
     .then(console.log);
   ```

3. **Verify:**
   - ✅ Queue status returns successfully
   - ✅ Force update enqueues with high priority
   - ✅ Update appears in queue status

### 5.2 Using Frontend Store

1. **Open browser console**

2. **Check if store is updating:**
   ```javascript
   // In Svelte dev mode, you can access stores
   // Check if updateQueueStatus is being set
   ```

## Step 6: Verify Real-time Updates

### 6.1 Multiple File Changes

1. **Modify multiple files** in quick succession

2. **Check:**
   - ✅ All updates are enqueued
   - ✅ Queue status shows correct pending count
   - ✅ Updates process in priority order
   - ✅ Frontend updates in real-time

### 6.2 Large File Update

1. **Modify a large file** (> 100 chunks)

2. **Verify:**
   - ✅ Update strategy is selected correctly
   - ✅ Processing time is reasonable
   - ✅ Frontend shows progress
   - ✅ Update completes successfully

## Step 7: Check Error Handling

### 7.1 Network Errors

1. **Stop backend server** temporarily

2. **Check frontend:**
   - ✅ No crashes
   - ✅ Errors are handled gracefully
   - ✅ Polling continues when server restarts

### 7.2 Invalid File Paths

1. **Try to force update with invalid path:**
   ```javascript
   fetch('http://localhost:8000/api/updates/force', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ file_path: '/invalid/path.txt' })
   })
     .then(r => r.json())
     .then(console.log);
   ```

2. **Verify:**
   - ✅ Error is returned gracefully
   - ✅ Frontend handles error appropriately

## Step 8: Performance Check

### 8.1 Update Speed

1. **Modify a small file** (< 10 chunks)

2. **Time the update:**
   - Should complete in < 5 seconds
   - Much faster than full re-index

3. **Check logs:**
   - Should see chunk-level update strategy
   - Only changed chunks processed

### 8.2 UI Responsiveness

1. **While updates are processing:**
   - ✅ UI remains responsive
   - ✅ No blocking operations
   - ✅ Other features still work

## Step 9: Visual Verification Checklist

- [ ] "Updating" badge appears in sidebar when updates are pending
- [ ] Badge disappears when updates complete
- [ ] No console errors
- [ ] Network requests are successful (200 status)
- [ ] Polling happens every ~2 seconds
- [ ] Queue status updates in real-time
- [ ] File modifications trigger updates
- [ ] Updates complete successfully
- [ ] UI remains responsive during updates

## Step 10: Browser Compatibility

Test in:
- [ ] Chrome/Edge (Chromium)
- [ ] Firefox
- [ ] Safari (if on Mac)

## Common Issues and Solutions

### Issue: "Updating" badge not appearing

**Check:**
1. Is polling active? (Network tab)
2. Are API calls successful? (200 status)
3. Is `updateQueueStatus` store being updated? (Console)
4. Check browser console for errors

**Solution:**
- Verify backend is running
- Check API endpoint: `GET /api/updates/queue`
- Verify store import in `+layout.svelte`

### Issue: Updates not triggering

**Check:**
1. Is FileMonitor running? (Backend logs)
2. Are file changes being detected? (Backend logs)
3. Is `enqueue_update` being called? (Backend logs)

**Solution:**
- Verify file is in monitored directory
- Check file extension is supported
- Verify FileMonitor is started

### Issue: Polling not working

**Check:**
1. Is `startUpdateQueuePolling()` called? (Check `+layout.svelte`)
2. Is interval being cleared? (Check `onDestroy`)
3. Are there JavaScript errors? (Console)

**Solution:**
- Verify `onMount` is calling `startUpdateQueuePolling()`
- Check for JavaScript errors
- Verify API service methods exist

## Quick Test Script

Run this in browser console to quickly test:

```javascript
// Test 1: Check if polling is active
console.log('Testing update queue polling...');

// Test 2: Get queue status
fetch('http://localhost:8000/api/updates/queue')
  .then(r => r.json())
  .then(data => {
    console.log('✅ Queue status:', data);
    if (data.queue) {
      console.log(`Pending: ${data.queue.pending}, Processing: ${data.queue.processing}`);
    }
  })
  .catch(err => console.error('❌ Error:', err));

// Test 3: Check if store exists (Svelte)
// This depends on your Svelte setup
```

## Success Criteria

✅ **All tests pass if:**
1. Update queue status displays correctly
2. File modifications trigger updates
3. Updates process successfully
4. UI updates in real-time
5. No console errors
6. Performance is acceptable
7. Error handling works

## Next Steps

If all tests pass:
- ✅ Frontend Phase 3.5 integration is complete
- ✅ System is ready for production use
- ✅ Monitor for any edge cases in real usage

If tests fail:
- Review error messages
- Check browser console
- Verify API endpoints
- Check network requests
- Review frontend code integration

