# Phase 2: Filename Trie for Fast Search - Planning Document

## Current State Analysis

### How Filename Search Works Now

1. **Database Search** (`database/service.py:310`)
   ```python
   IndexedDocument.file_path.ilike(f"%{query}%")  # SQL pattern matching
   ```
   - **Performance**: O(n) where n = number of files
   - **Method**: Full table scan with pattern matching
   - **Speed**: Slow for large directories (100+ files)

2. **LLM File Selection** (`orchestrator.py:441-514`)
   ```python
   # Sends ALL filenames to LLM, asks it to select
   file_list_str = "\n".join([f"{idx}. {filename}" for ...])
   response = await self.llm_service.generate_simple(selection_prompt)
   ```
   - **Performance**: O(1) LLM call, but expensive
   - **Method**: Sends all filenames to LLM for semantic selection
   - **Cost**: ~$0.001-0.01 per query (Gemini API)
   - **Speed**: 1-3 seconds per query
   - **Use Case**: Complex queries like "files NOT receipts"

### Current Limitations

| Issue | Impact | Example |
|-------|--------|---------|
| **Slow SQL search** | O(n) scan, slow with 100+ files | "sales" query scans all files |
| **Expensive LLM calls** | Cost adds up with many queries | Every filename query = LLM call |
| **No autocomplete** | Poor UX, no real-time suggestions | User types "sal" → no suggestions |
| **No prefix matching** | Must type full/partial words | "TCO" works, "TC" might not |
| **LLM overhead** | 1-3 second delay for simple queries | "show PDF files" = LLM call |

---

## What is a Filename Trie?

A **Trie (Prefix Tree)** is a tree data structure optimized for prefix-based searches.

### Structure Example

```
Root
├── s
│   ├── a
│   │   └── l
│   │       └── e
│   │           └── s
│   │               └── _report.pdf → file_path
│   └── u
│       └── m
│           └── m
│               └── a
│                   └── r
│                       └── y.pdf → file_path
├── t
│   └── c
│       └── o
│           ├── 001.pdf → file_path
│           └── 002.pdf → file_path
└── m
    └── e
        └── e
            └── t
                └── i
                    └── n
                        └── g.pdf → file_path
```

### Search Performance

- **Query**: "sales"
- **Current (SQL)**: Scans all files, checks each filename → O(n)
- **Trie**: Follows path `s → a → l → e → s` → O(m) where m = query length
- **Result**: Instant, regardless of number of files!

---

## Benefits of Filename Trie

### 1. **Performance: O(m) vs O(n)**

| Scenario | Current (SQL) | With Trie | Improvement |
|----------|--------------|-----------|-------------|
| 10 files, query "sales" | ~1ms | ~0.1ms | 10x faster |
| 100 files, query "sales" | ~10ms | ~0.1ms | 100x faster |
| 1000 files, query "sales" | ~100ms | ~0.1ms | 1000x faster |
| 10,000 files, query "sales" | ~1s | ~0.1ms | 10,000x faster |

**Key Insight**: Trie performance is **independent of file count**!

### 2. **Cost Savings: Eliminate LLM Calls**

**Current Flow:**
```
User: "show me TCO files"
  → LLM call ($0.001, 1-3s)
  → Returns file numbers
  → Query those files
```

**With Trie:**
```
User: "show me TCO files"
  → Trie search (0.1ms, $0)
  → Returns matching files instantly
  → Query those files
```

**Savings**: 
- **Cost**: $0.001-0.01 per filename query → $0
- **Speed**: 1-3 seconds → < 1ms
- **Scale**: 100 queries/day = $0.10-1.00/day saved

### 3. **Enhanced User Experience**

#### Autocomplete Support
```
User types: "sal"
  → Trie suggests: ["sales_report.pdf", "sales_data.xlsx"]
  → Instant feedback, no waiting
```

#### Real-time Search
```
User types: "TCO"
  → Results update as they type
  → No need to press Enter
  → IDE-like experience
```

#### Prefix Matching
```
Query: "TC" → Finds: ["TCO001.pdf", "TCO002.pdf", "TC004.pdf"]
Query: "sal" → Finds: ["sales_report.pdf", "sales_summary.docx"]
```

### 4. **Reduced LLM Dependency**

**Current**: Every filename query requires LLM
**With Trie**: Simple filename queries bypass LLM entirely

**Smart Routing:**
- **Simple queries** ("TCO files", "PDF files") → Trie (instant, free)
- **Complex queries** ("files NOT receipts", "documents about sales") → LLM (semantic)

---

## How It Affects Application Flow

### Current Flow

```
User Query: "show me TCO files"
    ↓
Query Classification (LLM) → "document"
    ↓
File Selection (LLM) → Files #1,2,5,8
    ↓
Hybrid Search → Semantic + BM25
    ↓
Response Generation (LLM)
    ↓
Response (5-10 seconds, $0.002-0.02)
```

### New Flow with Trie

```
User Query: "show me TCO files"
    ↓
Query Classification (LLM) → "document"
    ↓
Filename Detection → "TCO" detected
    ↓
Trie Search → Files matching "TCO" (0.1ms, $0)
    ↓
Hybrid Search → Only on selected files
    ↓
Response Generation (LLM)
    ↓
Response (3-7 seconds, $0.001-0.01)
```

**Improvements:**
- ✅ **2-3 seconds faster** (no LLM file selection)
- ✅ **50% cost reduction** (one less LLM call)
- ✅ **More accurate** (exact filename matches)

---

## Implementation Strategy

### Phase 2A: Basic Trie Implementation

**Goal**: Fast prefix matching for filenames

**Components:**
1. `FilenameTrie` class
2. Integration with metadata indexing
3. Fast search method

**Use Cases:**
- "TCO files" → Trie search
- "PDF files" → Trie + file type filter
- "files starting with SAL" → Trie prefix search

### Phase 2B: Smart Query Routing

**Goal**: Automatically choose Trie vs LLM

**Logic:**
```python
if is_simple_filename_query(query):
    # Use Trie (fast, free)
    files = trie.search(query)
else:
    # Use LLM (semantic, expensive)
    files = await llm_select_files(query)
```

**Detection Rules:**
- Contains filename patterns: "TCO", "sales", "invoice"
- Contains file type: "PDF", "DOCX"
- Contains prefix indicators: "files starting with", "files containing"
- Simple patterns: "show me X files"

### Phase 2C: Autocomplete API

**Goal**: Frontend autocomplete support

**New Endpoint:**
```
GET /api/documents/autocomplete?q=sales
→ Returns: ["sales_report.pdf", "sales_data.xlsx"]
```

**Frontend Integration:**
- Real-time suggestions as user types
- Click to select
- Keyboard navigation

---

## Performance Comparison

### Scenario: 1000 Files, Query "sales"

| Method | Time | Cost | Accuracy |
|--------|------|------|----------|
| **Current SQL** | ~100ms | $0 | 100% |
| **Current LLM** | 1-3s | $0.001 | 95% |
| **Trie** | ~0.1ms | $0 | 100% |

### Scenario: 10,000 Files, Query "TCO"

| Method | Time | Cost | Accuracy |
|--------|------|------|----------|
| **Current SQL** | ~1s | $0 | 100% |
| **Current LLM** | 2-5s | $0.001 | 90% (may miss some) |
| **Trie** | ~0.1ms | $0 | 100% |

**Winner**: Trie is **10,000x faster** and **free**!

---

## Integration Points

### 1. Metadata Indexing Integration

**When**: During `_build_metadata_index()`

```python
async def _build_metadata_index(self, directory_path: str):
    # ... existing metadata indexing ...
    
    # Add to Trie
    for file_path in supported_files:
        filename = Path(file_path).name
        self.filename_trie.add(filename, file_path)
```

**Benefit**: Trie built instantly with metadata (< 1ms per file)

### 2. Query Flow Integration

**When**: During `_select_relevant_files()`

```python
async def _select_relevant_files(self, question: str):
    # Check if simple filename query
    if self._is_simple_filename_query(question):
        # Use Trie (fast, free)
        matching_files = self.filename_trie.search(question)
        return matching_files
    
    # Otherwise, use LLM (semantic)
    return await self._llm_select_files(question)
```

**Benefit**: Smart routing, best of both worlds

### 3. Database Search Integration

**When**: During `search_documents()`

```python
async def search_documents(self, query: str, ...):
    # Fast pre-filter with Trie
    if query:
        trie_matches = self.filename_trie.search(query)
        if trie_matches:
            # Only search these files in database
            stmt = stmt.where(IndexedDocument.file_path.in_(trie_matches))
```

**Benefit**: Reduces database scan from O(n) to O(matched_files)

---

## Trade-offs & Considerations

### Pros ✅

1. **Massive performance gain**: 100-10,000x faster
2. **Cost savings**: Eliminate LLM calls for simple queries
3. **Better UX**: Autocomplete, real-time search
4. **Scalability**: Performance doesn't degrade with file count
5. **Accuracy**: 100% for exact/prefix matches

### Cons ⚠️

1. **Memory usage**: ~1KB per file (negligible for < 10,000 files)
2. **Maintenance**: Need to update Trie on file changes
3. **Complexity**: Additional code to maintain
4. **Not for semantic queries**: Still need LLM for "files about sales"

### When to Use Each

| Query Type | Method | Reason |
|------------|--------|--------|
| "TCO files" | **Trie** | Exact pattern match |
| "PDF files" | **Trie + Filter** | File type + Trie |
| "files starting with SAL" | **Trie** | Prefix match |
| "files about sales" | **LLM** | Semantic, needs content |
| "files NOT receipts" | **LLM** | Complex logic |
| "documents from October" | **LLM** | Semantic date matching |

---

## Implementation Plan

### Step 1: Create FilenameTrie Class
- Basic Trie structure
- Add/remove/search methods
- Case-insensitive support

### Step 2: Integrate with Metadata Indexing
- Build Trie during metadata indexing
- Update Trie on file changes
- Persist Trie (optional, for restart)

### Step 3: Smart Query Detection
- Detect simple filename queries
- Route to Trie or LLM appropriately
- Fallback to LLM if Trie fails

### Step 4: Frontend Integration
- Autocomplete API endpoint
- Real-time search suggestions
- Keyboard navigation

### Step 5: Performance Testing
- Benchmark vs current SQL search
- Measure cost savings
- Validate accuracy

---

## Expected Outcomes

### Performance Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Filename query time (100 files) | 10ms | 0.1ms | **100x faster** |
| Filename query time (1000 files) | 100ms | 0.1ms | **1000x faster** |
| LLM calls per day | 100 | 50 | **50% reduction** |
| Cost per day | $0.10 | $0.05 | **50% savings** |
| Autocomplete latency | N/A | < 10ms | **New feature** |

### User Experience

- ✅ **Instant filename search** (no waiting)
- ✅ **Autocomplete suggestions** (as you type)
- ✅ **Real-time filtering** (IDE-like experience)
- ✅ **Lower latency** (2-3 seconds faster queries)

---

## Conclusion

**Filename Trie is a high-impact, low-risk improvement:**

1. **Massive performance gain** (100-10,000x faster)
2. **Cost savings** (50% reduction in LLM calls)
3. **Better UX** (autocomplete, instant search)
4. **Scalability** (performance independent of file count)
5. **Smart routing** (Trie for simple, LLM for complex)

**Recommendation**: **Implement Phase 2** - The benefits far outweigh the minimal complexity added.

---

## Next Steps

1. Review and approve this plan
2. Implement `FilenameTrie` class
3. Integrate with metadata indexing
4. Add smart query routing
5. Test performance improvements
6. Deploy and monitor

