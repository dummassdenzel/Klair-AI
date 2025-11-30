# Testing Metadata-First Indexing

## Automated Tests

Run the comprehensive test suite:

```bash
cd ai
python tests/test_metadata_first_indexing.py
```

This will test:
1. ✅ Metadata indexing speed (< 1 second)
2. ✅ Immediate queryability after metadata indexing
3. ✅ Background content indexing
4. ✅ Status transitions (metadata_only → indexed)
5. ✅ Incremental updates

## Manual Testing Guide

### Step 1: Test Metadata Indexing Speed

1. **Start the backend:**
   ```bash
   cd ai
   .venv/Scripts/activate
   uvicorn main:app --reload
   ```

2. **Select a directory with multiple files** (10-50 files recommended)

3. **Watch the logs** - You should see:
   ```
   ✅ Metadata index built: X files in Y.XXs
   📁 Files are now queryable by filename/metadata
   🔄 Starting background content indexing...
   ```

4. **Verify speed:** Metadata indexing should complete in < 2 seconds even for 50 files

### Step 2: Test Immediate Queryability

1. **Immediately after selecting directory**, try these queries:
   - "list all files"
   - "show me all PDF files"
   - "what files are in this directory?"

2. **Expected behavior:**
   - ✅ Queries should work immediately (even before content indexing)
   - ✅ You should see all files listed
   - ✅ Files may show "Indexing in progress..." for content

### Step 3: Test Background Content Indexing

1. **After metadata indexing**, wait 10-30 seconds

2. **Check the database:**
   ```python
   # In Python shell or test script
   from database.database import get_db
   from database.models import IndexedDocument
   from sqlalchemy import select
   
   async for session in get_db():
       stmt = select(IndexedDocument)
       result = await session.execute(stmt)
       docs = result.scalars().all()
       
       indexed = [d for d in docs if d.processing_status == "indexed"]
       metadata_only = [d for d in docs if d.processing_status == "metadata_only"]
       
       print(f"Indexed: {len(indexed)}, Metadata-only: {len(metadata_only)}")
       break
   ```

3. **Expected behavior:**
   - ✅ Status should transition from "metadata_only" → "indexed"
   - ✅ Content queries should work after indexing completes

### Step 4: Test Content Queries

1. **After content indexing completes** (wait 30-60 seconds), try:
   - "What's in [filename]?"
   - "Summarize the documents"
   - "Find information about [topic]"

2. **Expected behavior:**
   - ✅ Queries should return relevant content
   - ✅ Sources should show content snippets
   - ✅ Chunks should be found

### Step 5: Test Incremental Updates

1. **Modify a file** in the watched directory

2. **Wait a few seconds** for file monitor to detect change

3. **Check logs** - Should see:
   ```
   Processed modification: [file_path]
   ```

4. **Query the modified file** - Should have updated content

## Performance Benchmarks

### Expected Performance

| Operation | Expected Time | Notes |
|-----------|--------------|-------|
| Metadata indexing (10 files) | < 0.5s | Instant |
| Metadata indexing (50 files) | < 1.0s | Still fast |
| Metadata indexing (100 files) | < 2.0s | Acceptable |
| Content indexing (1 file) | 2-5s | Background |
| Content indexing (10 files) | 10-30s | Background |
| Content indexing (50 files) | 1-3 min | Background |

### What to Look For

✅ **Good Signs:**
- Metadata indexing completes in < 2 seconds
- Files are queryable immediately
- Background indexing doesn't block UI
- Status transitions correctly
- Only changed files are re-indexed

❌ **Warning Signs:**
- Metadata indexing takes > 5 seconds
- Files not queryable after metadata indexing
- Background indexing blocks queries
- All files re-indexed on every change
- Status stuck in "metadata_only"

## Troubleshooting

### Issue: Metadata indexing is slow

**Possible causes:**
- Too many files (consider batching)
- Database connection issues
- File system access problems

**Solutions:**
- Check database connection
- Verify file permissions
- Check logs for errors

### Issue: Files not queryable immediately

**Possible causes:**
- Database not updated
- Query method not handling metadata_only status

**Solutions:**
- Check database for metadata_only documents
- Verify query method includes metadata_only in listing queries

### Issue: Background indexing not completing

**Possible causes:**
- LLM service unavailable
- Embedding model loading issues
- File extraction errors

**Solutions:**
- Check LLM provider configuration
- Verify embedding model is accessible
- Check logs for extraction errors

### Issue: Status not transitioning

**Possible causes:**
- Background task crashed
- Database update failed
- Processing errors

**Solutions:**
- Check background task logs
- Verify database updates
- Check for processing errors in logs

## Database Verification

Check document statuses:

```sql
-- In database client
SELECT 
    processing_status,
    COUNT(*) as count
FROM indexed_documents
GROUP BY processing_status;
```

Expected results:
- `metadata_only`: Files being indexed in background
- `indexed`: Fully indexed files
- `error`: Files that failed to index

## Log Analysis

Look for these log messages:

```
✅ Metadata index built: X files in Y.XXs
📁 Files are now queryable by filename/metadata
🔄 Starting background content indexing...
📊 Background indexing progress: X/Y files
✅ Background content indexing complete
```

If you see errors, check:
- LLM provider configuration
- Database connection
- File system permissions
- Embedding model availability

