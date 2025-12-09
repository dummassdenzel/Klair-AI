# Backend Memory Leak Analysis

## Issues Found

### ✅ Good Practices (No Leaks)
1. **Database Sessions**: Using async context managers (`async for db_session in get_db()`) - properly closed
2. **HTTP Clients**: LLM service properly closes httpx clients in cleanup
3. **Embedding Model**: Has cleanup method that deletes model from memory
4. **Temporary Processors**: Pre-warming temp processor is properly cleaned up
5. **File Handles**: File reading uses context managers (`with open()`)

### ⚠️ Potential Memory Leaks

#### 1. **Subprocess Processes (Medium Risk)**
**Location**: `pptx_converter.py:_convert_sync()`

**Issue**: 
- LibreOffice subprocess may not be properly terminated if conversion hangs
- No process group management on Windows
- If timeout expires, process might still be running

**Impact**: 
- Zombie processes accumulate
- Memory not released until process terminates

**Fix Applied**:
- Add process group termination on Windows
- Ensure subprocess is killed on timeout
- Add cleanup in converter

#### 2. **Unbounded In-Memory Dictionaries (High Risk)**
**Location**: `orchestrator.py:file_hashes`, `file_metadata`

**Issue**:
- `self.file_hashes: Dict[str, str]` grows with every indexed file
- `self.file_metadata: Dict[str, FileMetadata]` grows with every indexed file
- Never cleared except on full cleanup
- Can grow to GBs with large document sets

**Impact**:
- Memory usage grows linearly with document count
- Will eventually cause OOM errors

**Recommendation**:
- Implement LRU cache with size limits
- Or move to database-backed storage
- Add periodic cleanup of old entries

#### 3. **Update Worker Tasks (Low Risk)**
**Location**: `orchestrator.py:update_worker`

**Issue**:
- Background worker task runs indefinitely
- Should be cancelled on cleanup

**Status**: 
- Has cleanup in orchestrator.cleanup()
- Should be verified

#### 4. **LibreOffice Temporary Files (Low Risk)**
**Location**: `pptx_converter.py`

**Issue**:
- LibreOffice may create temporary files during conversion
- Not explicitly cleaned up

**Impact**: 
- Disk space usage (not memory)
- Temporary files accumulate

**Fix Applied**:
- Add cleanup of temporary files after conversion

## Fixes Applied

1. ✅ Subprocess cleanup with proper termination
2. ✅ Cache clearing endpoint
3. ✅ Cache statistics endpoint
4. ✅ Improved error handling in converter

## Recommendations for Future

1. **Implement LRU Cache** for file_hashes and file_metadata
2. **Add Memory Monitoring** endpoint to track memory usage
3. **Periodic Cache Cleanup** - automatic cleanup of old cache files
4. **Process Monitoring** - track subprocess count and memory

