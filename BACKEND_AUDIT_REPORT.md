# Backend Security & Optimization Audit Report

**Date**: 2026
**Scope**: Complete backend codebase review
**Focus**: Security vulnerabilities, performance issues, code quality, refactoring opportunities

---

## 🔴 CRITICAL SECURITY ISSUES

---

### 3. SQL Injection Risk — RESOLVED
**Location**: `ai/database/service.py` (`search_documents`)

**Issue** (was):
- Using `ilike` with user input in f-string pattern (risky-looking even though SQLAlchemy binds)

**Risk**: LOW (SQLAlchemy protects, but pattern was bad practice)

**Resolution**:
- Replaced with `func.lower(column).contains(func.lower(literal(query)))` using `literal(query)` so the search term is explicitly a bound parameter. Text search is case-insensitive and avoids the f-string pattern.

---

---

## ⚠️ HIGH PRIORITY ISSUES
---

### 10. Database Connection Management — RESOLVED
**Location**: `ai/database/service.py`, `ai/main.py`, orchestrator, update_executor

**Issue** (was):
- Using `async for session in get_db(): ... break` pattern
- If exception occurred before `break`, connection could stay open
- Risk of connection pool exhaustion in loops

**Risk**: MEDIUM (Resource leaks)

**Resolution**:
- **`ai/database/__init__.py`**: Exported `AsyncSessionLocal` for explicit session use.
- **`ai/database/service.py`**: All methods now use `async with AsyncSessionLocal() as session:` instead of `async for session in get_db(): ... break`. Write operations use `try: ... await session.commit(); return ... except Exception: await session.rollback(); raise`. Read-only operations use the context manager without commit. Session is always closed on exit (success or exception).
- **`ai/main.py`**: Replaced every `async for db_session in get_db():` with `async with AsyncSessionLocal() as db_session:` (chat document linking, get_documen t_file, get_document_preview, get_document_metadata).
- **Orchestrator and update_executor**: Same pattern — `AsyncSessionLocal()` context manager; commit/rollback where needed.
- **`get_db()`** remains in `database.py` for FastAPI `Depends(get_db)` if used by any route; production paths now use explicit sessions.

---

## 🟡 MEDIUM PRIORITY ISSUES

### 11. Missing Input Validation on Query Parameters
**Location**: `ai/main.py:870` (`autocomplete_filenames`)

**Issue**:
- No length limit on query string
- No sanitization
- Could cause performance issues with very long queries

**Fix**:
```python
@app.get("/api/documents/autocomplete")
async def autocomplete_filenames(q: str = "", limit: int = 10):
    # Validate inputs
    if len(q) > 200:
        raise HTTPException(status_code=400, detail="Query too long (max 200 chars)")
    if limit > 100:
        limit = 100  # Cap limit
    if limit < 1:
        limit = 1
    # ...
```

---

### 12. Error Information Leakage
**Location**: Multiple endpoints

**Issue**:
- Internal error messages exposed to clients
- Stack traces could leak system information

**Current Code**:
```python
raise HTTPException(status_code=500, detail=f"Failed to set directory: {str(e)}")
```

**Fix**:
```python
# In production, don't expose internal errors
if settings.ENVIRONMENT == "production":
    raise HTTPException(status_code=500, detail="Internal server error")
else:
    raise HTTPException(status_code=500, detail=f"Failed to set directory: {str(e)}")
```

---

### 13. Missing File Type Validation in Preview Endpoint
**Location**: `ai/main.py:987` (`get_document_preview`)

**Issue**:
- Only checks file_type from database
- Doesn't validate actual file extension matches
- Could serve wrong file type

**Fix**:
```python
# Validate file extension matches database record
actual_extension = path_obj.suffix.lower()
if actual_extension != f".{file_type}":
    logger.warning(f"File extension mismatch: DB says {file_type}, file is {actual_extension}")
    # Decide: trust DB or file? For security, validate both
```

---

### 14. No Timeout on Long-Running Operations
**Location**: OCR, PPTX conversion, document processing

**Issue**:
- No timeout on OCR operations (could hang indefinitely)
- No timeout on document processing
- Could cause resource exhaustion

**Fix**:
```python
import asyncio

async def process_with_timeout(coro, timeout=300):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"Operation timed out after {timeout}s")
        raise HTTPException(status_code=504, detail="Operation timed out")
```

---

### 15. File Monitor Extension Mismatch
**Location**: `ai/services/file_monitor.py:63`

**Issue**:
- File monitor has hardcoded extensions
- Doesn't sync with FileValidator/TextExtractor
- Missing `.pptx` and image extensions

**Current Code**:
```python
self.supported_extensions = {".pdf", ".docx", ".txt", ".xlsx", ".xls"}  # Missing .pptx and images
```

**Fix**:
```python
# Sync with FileValidator
from services.document_processor.extraction import FileValidator
file_validator = FileValidator(max_file_size_mb=50, ocr_service=ocr_service)
self.supported_extensions = file_validator.supported_extensions
```

---

## 🟢 LOW PRIORITY / OPTIMIZATION OPPORTUNITIES

### 16. Inefficient Database Queries
**Location**: `ai/database/service.py:290` (`search_documents`)

**Issue**:
- Separate count query (N+1 pattern)
- Could be optimized with single query using window functions

**Optimization**:
```python
# Use window function for count
from sqlalchemy import func, over

stmt = select(
    IndexedDocument,
    func.count(IndexedDocument.id).over().label('total_count')
).where(...).limit(limit).offset(offset)

# Get both results and count in one query
```

---

### 17. Redundant Path Normalization
**Location**: `ai/main.py:234-238`

**Issue**:
- Path normalized twice
- Redundant computation

**Fix**:
```python
# Normalize once
directory_path = os.path.normpath(os.path.abspath(directory_path))
normalized_current_path = os.path.normpath(os.path.abspath(current_directory)) if current_directory else None
# Remove second normalization
```

---

### 18. Missing Indexes on Database
**Location**: Database models

**Issue**:
- No explicit indexes on frequently queried fields
- `file_path`, `file_type`, `last_modified` should be indexed

**Fix**:
```python
# In models.py
class IndexedDocument(Base):
    file_path = Column(String, index=True)  # Add index
    file_type = Column(String, index=True)  # Add index
    last_modified = Column(DateTime, index=True)  # Add index
```

---

### 19. Large File Metadata in Memory
**Location**: `ai/services/document_processor/orchestrator.py:1177`

**Issue**:
- `get_stats()` returns full file metadata dictionary
- Could be large for many files
- Should paginate or summarize

**Fix**:
```python
def get_stats(self) -> Dict:
    return {
        "total_files": len(self.file_hashes),
        "total_chunks": collection_count,
        # Don't return full indexed_files list for large datasets
        "indexed_files_count": len(self.file_hashes),
        "indexed_files_sample": list(self.file_hashes.keys())[:10],  # Sample only
        # ...
    }
```

---

### 20. No Connection Pooling Configuration
**Location**: `ai/database/database.py:11`

**Issue**:
- No explicit connection pool settings
- Could exhaust connections under load

**Fix**:
```python
engine = create_async_engine(
    async_database_url,
    echo=settings.SQLALCHEMY_ECHO,
    pool_size=10,  # Max connections
    max_overflow=20,  # Additional connections
    pool_pre_ping=True,  # Verify connections
    pool_recycle=3600  # Recycle connections after 1 hour
)
```

---

## 📊 CODE QUALITY ISSUES

### 21. Inconsistent Error Handling
**Location**: Multiple files

**Issue**:
- Some functions return `None` on error, others raise exceptions
- Inconsistent error messages

**Recommendation**: Standardize error handling pattern

---

### 22. Magic Numbers
**Location**: Multiple files

**Issue**:
- Hardcoded values (timeouts, limits, sizes)
- Should be in config

**Examples**:
- `max_queue_size=100` (file_monitor.py:52)
- `debounce_delay = 2.0` (file_monitor.py:59)
- `max_history=1000` (main.py:41)

**Fix**: Move to config.py

---

### 23. Missing Type Hints
**Location**: Some functions

**Issue**:
- Not all functions have complete type hints
- Reduces code clarity and IDE support

**Recommendation**: Add comprehensive type hints

---

### 24. Duplicate Code
**Location**: File validation logic

**Issue**:
- Similar validation logic in multiple places
- FileValidator exists but not always used

**Recommendation**: Centralize validation

---

## 🔧 REFACTORING OPPORTUNITIES

### 25. Extract File Serving Logic
**Location**: `ai/main.py:896-985`

**Issue**:
- Large function handling multiple file types
- Should be split into smaller functions

**Refactor**:
```python
class FileServingService:
    def __init__(self, current_directory: str):
        self.current_directory = current_directory
    
    def validate_file_access(self, file_path: str) -> Path:
        # Centralized validation
        pass
    
    async def serve_text_file(self, file_path: Path) -> Response:
        # Handle text files
        pass
    
    async def serve_binary_file(self, file_path: Path, content_type: str) -> FileResponse:
        # Handle binary files
        pass
```

---

### 26. Configuration Management
**Location**: `ai/config.py`

**Issue**:
- Settings class mixes concerns
- No validation of config values
- No environment-specific configs

**Refactor**:
```python
from pydantic import BaseSettings, validator

class Settings(BaseSettings):
    DATABASE_URL: str
    MAX_FILE_SIZE_MB: int = 50
    
    @validator('MAX_FILE_SIZE_MB')
    def validate_file_size(cls, v):
        if v < 1 or v > 1000:
            raise ValueError("File size must be between 1 and 1000 MB")
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = False
```

---

## 📋 PRIORITY SUMMARY

### 🔴 Critical (Fix Immediately)
1. Path traversal vulnerability in file serving
2. No input validation on directory path
3. No rate limiting
4. Unbounded memory growth
5. Global state pattern (multi-tenancy blocker)

### ⚠️ High Priority (Fix Soon)
6. Shared vector store (data leakage)
7. No query result caching
8. Database connection management
9. Missing file size limits on text files
10. File monitor extension mismatch

### 🟡 Medium Priority (Plan to Fix)
11. Input validation on query parameters
12. Error information leakage
13. Missing file type validation
14. No timeout on long operations
15. Inefficient database queries

### 🟢 Low Priority (Optimize When Time Permits)
16. Redundant path normalization
17. Missing database indexes
18. Large metadata in memory
19. Connection pooling configuration
20. Code quality improvements

---

## 🎯 RECOMMENDED ACTION PLAN

### Phase 1: Security Fixes (Week 1)
1. Add path validation to file serving endpoints
2. Add input validation to directory selection
3. Implement rate limiting
4. Add file size limits

### Phase 2: Scalability Fixes (Week 2)
5. Fix unbounded memory growth (LRU cache)
6. Implement query result caching
7. Fix database connection management
8. Add connection pooling

### Phase 3: Architecture Improvements (Week 3-4)
9. Remove global state (session-based architecture)
10. Implement per-directory vector store isolation
11. Add proper error handling
12. Add timeouts to long operations

### Phase 4: Optimization (Ongoing)
13. Database query optimization
14. Add missing indexes
15. Code quality improvements
16. Refactoring opportunities

---

## ✅ WHAT'S WORKING WELL

1. **SQL Injection Protection**: SQLAlchemy properly parameterizes queries
2. **Async Architecture**: Good use of async/await throughout
3. **Error Logging**: Comprehensive logging in place
4. **Modular Design**: Clean separation of concerns
5. **Type Hints**: Good type hint coverage (could be better)
6. **Database Models**: Well-structured database schema
7. **Service Pattern**: Good use of service classes

---

## 📝 NOTES

- Most issues are fixable without major architecture changes
- Security issues should be addressed first
- Memory issues will become critical with scale
- Multi-tenancy requires architectural changes (Phase 3)

**Estimated Effort**:
- Phase 1 (Security): 2-3 days
- Phase 2 (Scalability): 3-5 days  
- Phase 3 (Architecture): 1-2 weeks
- Phase 4 (Optimization): Ongoing

