# Orchestrator Refactoring Test Suite

## Overview

This test suite validates that the orchestrator refactoring was successful and that all the key improvements are working correctly.

## Test Categories

### ✅ Critical Tests (Must Pass)

1. **Retrieval Pipeline Test**
   - Validates that the unified retrieval pipeline works correctly
   - Tests: semantic search → BM25 boost → reranking
   - **Success Criteria**: Pipeline executes and returns documents

2. **Configuration Externalization**
   - Validates that retrieval parameters are externalized in `query_config.py`
   - Tests: `retrieval_config` attribute exists and methods work
   - **Success Criteria**: Configuration class accessible and functional

3. **Pattern Matching Removal**
   - Validates that all brittle pattern lists are removed
   - Tests: Removed methods (`_rewrite_query`, `_is_simple_filename_query`, etc.)
   - Tests: Removed pattern lists (`enumeration_patterns`, `listing_query_patterns`, etc.)
   - **Success Criteria**: No pattern matching code remains

4. **Enumeration Query Handling**
   - Validates that enumeration queries use the unified pipeline (no special handling)
   - Tests: "list all speakers", "who attended?", etc.
   - **Success Criteria**: All enumeration queries classified as `document_search` and use retrieval pipeline

### ⚠️ Non-Critical Tests (May Fail Due to API Quota)

5. **Query Classification**
   - Tests unified query classification (greeting, general, document_listing, document_search)
   - **Note**: Requires LLM API calls, may fail if quota exceeded
   - **Success Criteria**: At least some classifications work correctly

6. **Explicit Filename Detection**
   - Tests `_find_explicit_filename()` method
   - **Success Criteria**: Quoted filenames are detected correctly

7. **Document Listing Queries**
   - Tests that listing queries return document lists
   - **Note**: Requires LLM API calls, may fail if quota exceeded
   - **Success Criteria**: Query type is `document_listing` and sources are returned

8. **Document Search Queries**
   - Tests that search queries use retrieval pipeline
   - **Note**: Requires LLM API calls, but retrieval should still work
   - **Success Criteria**: Retrieval pipeline executes (even if LLM fails)

## Running the Tests

```bash
cd ai
.venv\Scripts\activate  # Windows
python tests/test_orchestrator_refactored.py
```

## Expected Results

### ✅ Successful Refactoring

If the refactoring was successful, you should see:
- ✅ Retrieval pipeline test: PASS
- ✅ Configuration test: PASS
- ✅ Pattern matching removal: PASS
- ✅ Enumeration queries: PASS (using retrieval pipeline)
- ⚠️ Some LLM-dependent tests may fail due to API quota

### ❌ Refactoring Issues

If there are issues, you may see:
- ❌ Retrieval pipeline fails (critical)
- ❌ Pattern matching code still exists (critical)
- ❌ Enumeration queries use special handling (critical)

## Key Validations

### 1. Single Retrieval Pipeline

**Before Refactoring:**
- Enumeration queries bypassed retrieval pipeline
- Direct `collection.get()` calls
- Arbitrary scoring (0.01)

**After Refactoring:**
- All queries use: semantic search → BM25 → reranking
- No direct collection access
- Proper relevance scoring

### 2. No Pattern Matching

**Before Refactoring:**
- `enumeration_patterns = ['list all', 'all speakers', ...]`
- `listing_query_patterns = ['list', 'all documents', ...]`
- `_is_simple_filename_query()` with 50+ lines of patterns

**After Refactoring:**
- All pattern lists removed
- Classification uses LLM (semantic understanding)
- Only explicit filename detection (quoted filenames)

### 3. Configuration Externalized

**Before Refactoring:**
- Magic numbers scattered throughout code
- Hardcoded `top_k=15`, `rerank_top_k=10`, etc.

**After Refactoring:**
- `RetrievalConfig` class in `query_config.py`
- Parameters based on query type
- Easy to adjust without code changes

### 4. Simplified File Selection

**Before Refactoring:**
- Trie search + LLM selection + pattern extraction (150+ lines)
- Pre-filtering files with LLM

**After Refactoring:**
- Path 1: Explicit filename → Trie lookup
- Path 2: Everything else → Trust retrieval relevance
- No LLM pre-filtering

## Troubleshooting

### API Quota Errors

If you see `429 You exceeded your current quota`:
- This is expected for free-tier Gemini API
- Critical tests (retrieval pipeline, configuration, pattern removal) don't require LLM
- Wait 30 seconds and retry, or use a different LLM provider

### Permission Errors on Cleanup

If you see `PermissionError: [WinError 32]`:
- This is a Windows file locking issue with ChromaDB
- Not critical - test directory will be cleaned up on next run
- Can be ignored

## Success Criteria Summary

The refactoring is successful if:

1. ✅ **Retrieval Pipeline**: All queries flow through unified pipeline
2. ✅ **No Pattern Matching**: All brittle pattern lists removed
3. ✅ **Configuration**: Parameters externalized in `query_config.py`
4. ✅ **Enumeration Queries**: Use retrieval pipeline (no special handling)
5. ✅ **Code Reduction**: Orchestrator reduced from ~1000 to ~600 lines
6. ✅ **Single Responsibility**: Methods are focused and under 50 lines

## Next Steps

After tests pass:
1. Test with real queries in the web application
2. Verify enumeration queries return comprehensive results
3. Monitor performance (should be similar or better)
4. Check logs for any unexpected behavior

