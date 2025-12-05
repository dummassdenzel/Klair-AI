# Orchestrator Refactoring Plan

## Overview
Comprehensive refactoring to remove brittle pattern matching, simplify query processing, and consolidate to a single retrieval pipeline.

## Architecture Changes

### Before (Current)
```
query()
├── _classify_query() → greeting/general/document
├── _rewrite_query() → extra LLM call
├── Pattern matching (listing_query_patterns, enumeration_patterns)
├── _is_simple_filename_query() → 50+ lines of patterns
├── _extract_filename_patterns() → complex extraction
├── _select_relevant_files() → Trie + LLM selection
├── Special handling for listing queries (bypasses retrieval)
├── Special handling for enumeration queries (bypasses retrieval)
└── Hybrid search → reranking → LLM
```

### After (Refactored)
```
query()
├── _classify_query() → greeting/general/document_listing/document_search
├── _find_explicit_filename() → simple quoted/pattern detection
├── _get_document_listing() → database listing (only for document_listing)
├── _retrieve_chunks() → single pipeline for all document_search queries
└── Enhanced LLM prompt for comprehensive extraction
```

## Code to Delete

### Methods to Remove Entirely
1. `_rewrite_query()` (lines ~967-1020) - ~53 lines
2. `_is_simple_filename_query()` (lines ~597-669) - ~72 lines
3. `_extract_filename_patterns()` (lines ~671-720) - ~49 lines
4. `_llm_select_files()` (lines ~784-887) - ~103 lines
5. Enumeration query detection code (lines ~1141-1147, ~1430-1461) - ~40 lines
6. Listing query pattern matching (lines ~1130-1137) - ~8 lines

**Total lines to remove: ~325 lines**

### Pattern Lists to Remove
- `listing_query_patterns` (lines 1130-1136)
- `enumeration_patterns` (lines 1141-1146)
- `filename_indicators` (lines 615-627)
- `file_type_patterns` (lines 630-639)
- `complex_indicators` (lines 646-660)
- `follow_up_indicators` (lines 944-945)
- `ambiguous_indicators` (lines 987-991)

## Code to Refactor

### 1. `_classify_query()` - Simplify and Unify
**Current:** Returns 'greeting', 'general', 'document'
**New:** Returns 'greeting', 'general', 'document_listing', 'document_search'

**Changes:**
- Remove pattern matching for follow-up indicators
- Add 'document_listing' category
- Simplify prompt
- Remove heuristic overrides

### 2. `_select_relevant_files()` - Simplify to Trie Only
**Current:** Trie search → LLM selection → complex logic
**New:** Only use Trie for explicit filenames, otherwise return None

**Changes:**
- Remove `_is_simple_filename_query()` call
- Remove `_extract_filename_patterns()` call
- Remove `_llm_select_files()` call
- Add simple `_find_explicit_filename()` method
- Return None for all non-explicit queries (let retrieval handle it)

### 3. `query()` - Single Pipeline
**Current:** Multiple special cases, pattern matching, bypasses
**New:** Unified flow through single retrieval pipeline

**Changes:**
- Remove query rewriting
- Remove listing query pattern matching
- Remove enumeration query detection
- Remove special enumeration handling (collection.get() bypass)
- Add `_get_document_listing()` for document_listing queries
- Add `_retrieve_chunks()` for all document_search queries
- Enhance LLM prompt for comprehensive extraction

## New Methods to Add

### 1. `_find_explicit_filename(question: str) -> Optional[str]`
Simple detection for quoted filenames or obvious patterns.
~15 lines

### 2. `_get_document_listing() -> QueryResult`
Handles document_listing queries using database.
~60 lines

### 3. `_retrieve_chunks(query, query_type, explicit_filename) -> tuple`
Single retrieval pipeline for all document_search queries.
~100 lines

## Configuration Externalization

### New File: `query_config.py`
Contains `RetrievalConfig` class with:
- Retrieval parameters per query type
- Source limiting
- BM25 boost settings

## Enhanced LLM Prompts

### For Document Listing
```
Provide a clear, organized list of ALL documents.
Be comprehensive and list ALL documents mentioned.
```

### For Document Search (Comprehensive Extraction)
```
- If the question asks for a list (e.g., "list all speakers"), be thorough and include ALL items
- If information appears in multiple chunks, combine it into a complete answer
- Use ALL relevant information from the documents
```

## Migration Steps

1. ✅ Create `query_config.py`
2. Add `_find_explicit_filename()` method
3. Refactor `_classify_query()` to return 4 types
4. Simplify `_select_relevant_files()` to use only Trie
5. Add `_get_document_listing()` method
6. Add `_retrieve_chunks()` method
7. Refactor `query()` to use new methods
8. Remove all deleted methods
9. Remove all pattern lists
10. Update imports to include `query_config`

## Testing Strategy

### Queries to Test

**Enumeration-style (should work WITHOUT special handling):**
- "List all speakers in the meeting notes"
- "Who attended the conference?"
- "Give me every participant mentioned"
- "What are all the deliverables?"

**Listing queries:**
- "What documents do we have?"
- "Show me all files"
- "List all PDFs"

**Specific queries:**
- "What's in sales_report.pdf?"
- "Who is the driver in TCO005?"
- "Summarize the contract"

**Conversational (should work WITHOUT query rewriting):**
- [After discussing TCO005] "Who drove that?"
- [After listing files] "Tell me more about the first one"

## Success Criteria

✅ Enumeration detection code completely removed
✅ Query rewriting code completely removed
✅ All queries use same retrieval pipeline (only parameters differ)
✅ No pattern matching lists (or minimal, well-justified ones)
✅ Orchestrator reduced by 30-40% LOC
✅ No direct vector store access outside designated methods
✅ All configuration values externalized
✅ Clear separation: retrieval concerns vs generation concerns

