# AI Pipeline Audit — Phased Fix Plan
**Audit Date:** April 15, 2026  
**Auditor:** AI Engineer Review  
**Status:** [ ] In Progress

---

## How to Use This Document

Work through each phase in order. Each phase is self-contained and builds on the previous.  
Before starting a phase, mark it **In Progress**. After all items in a phase are verified, mark it **Complete**.

Severity labels:
- 🔴 **Critical** — Correctness bug or silent failure
- 🟠 **High** — Significant architectural or reliability problem
- 🟡 **Medium** — Performance, design, or maintainability issue
- 🟢 **Low** — Polish, safety, or convention improvement

---

## Phase 1 — Critical Correctness Bugs
**Goal:** Fix silent failures and data correctness issues that affect every user session.  
**Status:** [ ] In Progress

---

### 1.1 — BM25 Index Is Empty After Restart 🔴 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py` → `_load_existing_metadata()`

**Problem:**  
When the app restarts, the SQLite database shows all files as `"indexed"`, but the BM25 index is in-memory only and is not rebuilt. The startup method (`_load_existing_metadata`) reloads the filename trie and the LRU metadata cache from the DB, but does not rebuild BM25. Because content indexing skips files already in the DB with a matching hash, BM25 stays empty permanently until files actually change on disk.

**Impact:** Keyword search contributes nothing after any restart. Hybrid search silently degrades to semantic-only with no indication to the user.

**Fix:**  
In `_load_existing_metadata()`, after loading documents from the DB, fetch the stored chunks from ChromaDB for each indexed file and re-populate the BM25 index. Alternatively, persist the BM25 index to disk (serialized) and reload it on startup rather than rebuilding from scratch.

**Verification:** Restart the backend with an already-indexed folder. Run a query containing exact keywords from a document. Confirm BM25 hits are logged in the retrieval step.

---

### 1.2 — Metadata Quick-Hash Breaks Incremental Update Detection 🔴 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py` → `_build_metadata_index()`

**Problem:**  
During the fast metadata phase, the stored hash is:
```python
quick_hash = f"{file_path}:{stat_info.st_mtime}"   # e.g. "C:/docs/file.pdf:1713123456.789"
```
During content indexing, the real hash is computed by `calculate_file_hash()` which returns an MD5 or SHA hex string.  
The check `if stored_hash == current_hash` always fails because the formats are incompatible. Every file is re-read, re-chunked, and re-embedded on every content indexing pass, even if nothing changed.

**Fix:**  
Option A (simple): Set `quick_hash = ""` (empty string) during metadata indexing. The content indexing check `if stored_hash == current_hash` will then only skip files that were previously content-indexed (real hash stored), which is the correct behavior.  
Option B (complete): Use the real `calculate_file_hash()` even during the metadata phase. This defeats the "fast scan" intent slightly but eliminates the discrepancy entirely.

**Verification:** Index a folder. Restart background indexing without changing files. Confirm log output shows "unchanged, skipping" for all files rather than re-processing each one.

---

### 1.3 — Query Cache Never Hits (Streaming Path Bypasses It) 🔴 ✅ COMPLETE

**File:** `ai/routers/chat.py` → `chat_stream()`

**Problem:**  
The query cache is checked and populated only in the non-streaming `POST /api/chat` handler. The frontend always uses `POST /api/chat/stream`. The streaming handler has no cache check at all. Every query goes to the LLM regardless of whether the identical question was just answered.

Additionally, the cache is never invalidated when documents change (new file indexed, file modified), so a cached answer could be stale.

**Fix:**  
1. Added `clear()` method to `QueryCache` (`ai/query_cache.py`).  
2. Added `set_post_index_hook()` to `DocumentProcessorOrchestrator` (`orchestrator.py`). The hook is called at the end of `_index_content_background`'s `finally` block (but only when not shut down), so the cache is invalidated as soon as the background indexing pass finishes.  
3. In `chat_stream`, resolved `cache` and `cache_key` before `event_generator` is defined. Added a cache-hit early-return at the top of `event_generator` that yields the cached `meta`, `token`, and `done` events and returns without touching the LLM. Added a cache-populate step after the stream completes successfully (non-empty `final_message` only).  
4. Aligned the non-streaming `/chat` cache payload to include the same extra fields (`query_type`, `retrieval_count`, `rerank_count`) so hits served via either path return consistent data.  
5. In `set_directory` (`routers/documents.py`), the query cache is cleared immediately on every directory switch, and the post-index hook is registered to clear it again once background indexing finishes.

**Verification:** Send the same message twice in a streaming session. Confirm the second response is served from cache and does not trigger an LLM call (check logs for "Stream query cache hit").

---

### 1.4 — Relevance Score Is Meaningless (Magic ×50 Multiplier) 🔴 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py` → `_retrieve_and_build_context()`

**Problem:**  
```python
"relevance_score": round(min(1.0, avg_score * 50), 3),
```
The ChromaDB collection uses `hnsw:space = cosine`, so it returns `distance = 1 − cosine_similarity`. The code converts this back to `base_score = 1 − distance = cosine_similarity`, which is already in [0, 1]. With the `* 50` multiplier any document with cosine similarity above 0.02 (nearly everything returned) shows as 100% relevant. All meaningful signal is lost.

**Fix:**  
Removed `* 50` and the now-redundant `min(1.0, ...)` wrapper from both the single-file and multi-file source-building paths in `_retrieve_and_build_context()`:
```python
"relevance_score": round(avg_score, 3),
```
The `avg_score` is the average of `final_score` values (cosine similarity + optional 0.1 BM25 boost, clamped to 1.0), which is already a meaningful [0, 1] number that preserves relative differences between documents.

**Verification:** Run a query for content not present in your documents. Confirm source scores are low (< 0.5) rather than 1.0. Run a query for content that is present; confirm the best-match document scores higher than weaker matches.

---

## Phase 2 — Architecture: Eliminate Dead Code and Fix Hybrid Search
**Goal:** Remove code that was replaced but not deleted, and wire up the actual RRF fusion that was built but never used.  
**Status:** [ ] In Progress

---

### 2.1 — Wire Up `HybridSearchService` RRF Fusion 🟠 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py` → `_retrieve_chunks()`  
**File:** `ai/services/document_processor/retrieval/hybrid_search.py`

**Problem:**  
`HybridSearchService` with correct Reciprocal Rank Fusion (RRF) is fully implemented and instantiated (`self.hybrid_search = HybridSearchService(k=60)`), but its `fuse_results()` method is never called. Instead, `_retrieve_chunks()` does manual ad-hoc score boosting:
```python
boost = self.retrieval_config.bm25_boost if (fp, cid) in bm25_hits else 0.0
final_score = min(1.0, base_score + boost)
```
This only benefits chunks that appeared in semantic results already. A document that ranks #1 in BM25 but did not appear in semantic results gets no benefit at all, defeating the recall expansion purpose of hybrid search.

**Fix:**  
Replaced the manual boost block entirely with RRF fusion:

1. **ID alignment**: ChromaDB IDs are `"{file_path}_chunk_{chunk_id}"` but BM25 IDs are `"{file_path}:{chunk_id}"`. Rather than migrating stored data, both sides are converted to the stable key `f"{file_path}:{chunk_id}"` derived from metadata before passing to `fuse_results()`.  
2. **`fuse_results()` call**: Both `semantic_list` and `keyword_list` are passed in `(id, score, metadata)` format. The returned `fused` list is sorted by RRF score — chunks that appear in both result sets rank highest, then semantic-only, then BM25-only.  
3. **Text recovery for BM25-only results**: Added `BM25Service.get_texts(chunk_ids)` which looks up document text from the in-memory corpus. After fusion, any chunk ID not found in the semantic text lookup is fetched from this helper.  
4. **Display score**: `score` stored per chunk is the original cosine similarity for semantic results, and `0.0` for BM25-only results (no embedding signal available). Their content still reaches the LLM context; only the citation display score is 0.  
5. **Cleanup**: Removed the now-unused `bm25_boost: float` field from `RetrievalConfig`.

**Verification:** Add a document with unique keywords not present in other docs. Query using those exact keywords. Confirm the document appears in results even if it did not rank in the semantic top-k (check logs for "Hybrid RRF" line showing keyword_results > 0).

---

### 2.2 — Eliminate the Duplicate `query` / `query_stream` Implementation 🟠 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py`

**Problem:**  
The following pairs of methods share 90%+ identical logic:
- `query()` and `query_stream()`
- `_query_via_tool_loop()` and `_query_stream_via_tool_loop()`
- `_query_via_planner_fallback()` and `_query_stream_via_planner_fallback()`

Any bug fixed in one is silently still present in the other. Any feature added must be added twice.

**Fix:**  
Introduced a unified `_run_shared_pipeline(question, history) → dict` that handles all routing (tool loop → planner → legacy classifier). It returns a pipeline-result dict with an `action` discriminant:
- `"direct"` — answer is pre-built (greeting, listing, no-results fallback)
- `"chat_messages"` — tool-loop path; finish by calling `chat_messages_stream(messages)`
- `"rag_context"` — planner / legacy-search path; finish by calling `generate_response` / `generate_response_stream`

Supporting helpers extracted:
- `_execute_tool_calls(tool_calls)` — runs tool execution loop with timeout/error handling; was duplicated 4× across the old methods
- `_pipeline_tool_loop(question, history, start_time)` — replaces both old tool-loop methods
- `_pipeline_planner(question, history, start_time)` — replaces both old planner methods
- `_pipeline_legacy(question, history, start_time)` — the shared legacy classifier path (extracted from inline code in `query`/`query_stream`)

`query()` and `query_stream()` are now thin wrappers: call `_run_shared_pipeline`, then differ only in how they consume the final generation step (`generate_response` vs `generate_response_stream`, or buffer vs stream `chat_messages_stream`).

The 6 old methods (`_query_via_tool_loop`, `_query_stream_via_tool_loop`, `_query_via_planner_fallback`, `_query_stream_via_planner_fallback`, plus the inline legacy paths in `query`/`query_stream`) have been deleted.

**Verification:** Run the same query against both `POST /api/chat` and `POST /api/chat/stream`. Both should return the same answer, sources, and query_type.

---

### 2.3 — Remove `HybridSearchService` Dead Instantiation (After 2.1) 🟡 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py`

**Problem:**  
After fixing 2.1 and properly using `HybridSearchService`, confirm the old manual boost code is fully removed. Do not leave both paths in place.

**Fix:**  
The manual boost block (`bm25_hits` set, `boost` calculation, `min(1.0, base_score + boost)`) was fully replaced during Phase 2.1. The `bm25_boost` field was also removed from `RetrievalConfig`. Only the RRF path remains.

**Verification:** `bm25_boost` no longer appears anywhere in the codebase.

---

## Phase 3 — Chunking: Character-Count to Token-Count
**Goal:** Make chunking semantically correct and aligned with model constraints.  
**Status:** [x] Phase 3.1 Complete

---

### 3.1 — Switch Chunker to Token-Based Sizing 🟠 ✅ COMPLETE

**File:** `ai/services/document_processor/extraction/chunker.py`

**Problem:**  
`DocumentChunker` measured chunk size in characters. LLMs and embedding models operate on tokens. The default `CHUNK_SIZE=1000` characters was approximately 250 tokens — very small. The embedding model `BAAI/bge-small-en-v1.5` has a 512-token maximum input. The relationship between `CHUNK_SIZE` and model capacity was invisible in configuration and would produce surprising behavior if the model is swapped.

**Fix:**
- `DocumentChunker` now accepts `chunk_size` (tokens), `chunk_overlap` (tokens), and `max_tokens` (hard cap).
- `_count_tokens(text)` uses the real HuggingFace tokenizer when available (wired via `set_tokenizer()`), falling back to `len(text) // 4` (conservative 4 chars/token estimate).
- `_trim_to_max_tokens(text)` enforces the hard cap after boundary detection; uses tokenizer-level truncation with a char-based fallback.
- `_find_chunk_boundary()` now uses span-relative lookback distances (no longer reads `self.chunk_size` in character units), so it works correctly for any window size.
- `EmbeddingService.get_tokenizer()` added — returns `embed_model.tokenizer` (lazy-loads the model if needed).
- Tokenizer is lazily wired into the chunker inside `add_document()` immediately after the first `encode_texts()` call, so the model is guaranteed to be loaded.
- Config defaults updated: `CHUNK_SIZE=300` tokens, `CHUNK_OVERLAP=50` tokens, new `MAX_CHUNK_TOKENS=512`.
- Orchestrator constructor updated with matching token-unit defaults and a new `max_chunk_tokens` parameter; `documents.py` passes `settings.MAX_CHUNK_TOKENS`.

**Verification:** Print token counts for 10 chunks from a sample document. Confirm they fall within the model's token limit.

---

### 3.2 — Fix Chunk Boundary Detection 🟡 ✅ COMPLETE

**File:** `ai/services/document_processor/extraction/chunker.py` → `_find_chunk_boundary()`

**Problem:**  
The old boundary detection split on `.!?` followed by any whitespace. This fired incorrectly on:
- Abbreviations: `e.g. something`, `i.e. the`, `Mr. Smith`, `Dr. Jones`
- Decimal numbers followed by space: `3.5 mm`, `99.9 %` (though `.` without space was already safe)
- File paths / URLs: these had no space after `.` so the original check didn't fire — already safe

**Fix (zero new dependencies):**
- `!` and `?` — kept as unambiguous sentence terminators (whitespace-followed check unchanged).
- `.` — after confirming the next character is whitespace, scan past all spaces to find the first non-space character. Split **only** if that character is uppercase (indicating a true new sentence) or end-of-text. Lowercase or digit after the whitespace means it is an abbreviation or continuation; no split occurs.
- Lookback distances remain proportional to the window span (introduced in 3.1), so the method still works correctly at any chunk size.

**Why not `nltk`/`spacy`?** Zero new dependencies and the uppercase heuristic covers the vast majority of real-world document text. The one remaining false positive is title abbreviations (`Mr. Smith`) where the name starts with uppercase — acceptable given rarity in business document content and overlapping chunk windows.

**Verification:** Run the chunker on a document containing decimal numbers and abbreviations. Confirm no mid-sentence splits.

---

## Phase 4 — Performance: Reduce LLM Call Count
**Goal:** Cut the number of LLM calls per query without degrading quality.  
**Status:** [ ] Not Started

---

### 4.1 — Eliminate Planner Call for Simple Queries 🟡 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py` → `_run_shared_pipeline()`

**Problem:**  
Every query — including "hello" and "thank you" — entered the planner LLM call before the actual response. For Ollama users (local), this doubled the minimum latency for every message.

**Fix:**  
`QueryClassifier` was already pure heuristic (regex + word matching, **zero LLM calls**). A classifier pre-filter was added to `_run_shared_pipeline()` on the planner path, before any LLM is invoked:

- `GREETING` / `GENERAL` → `_generate_direct_response()` — **1 LLM call** (was 2)
- `DOCUMENT_LISTING` → `_get_document_listing()` — **0 LLM calls** (was 2; it's a pure DB query)
- `DOCUMENT_SEARCH` → planner as before — **2 LLM calls** (unchanged)

The tool-calling path (Groq) is unaffected — the LLM there already decides tool use natively in a single inference call.

The change is entirely in `_run_shared_pipeline()`. No other methods were modified.

**Verification:** Send "hello" to the backend. Confirm only one LLM call is made (the `_generate_direct_response` call), not two. Send "list my files" — confirm zero LLM calls are made (DB query only).

---

### 4.2 — Gate Context Compression to High-Value Cases Only 🟡 ✅ COMPLETE

**File:** `ai/config.py`  
**File:** `ai/services/document_processor/orchestrator.py` → `_retrieve_and_build_context()`

**Problem:**  
Context compression called the LLM **once per retrieved chunk** (all in parallel) for any multi-file query with ≥ 2 documents and ≥ 2,000 characters of context — which is almost every document search. On the planner path this added a third layer of LLM overhead. With 5 retrieved chunks, that was 5 extra LLM calls. On local Ollama, "parallel" calls still hit the same GPU sequentially, adding 5–15 seconds per query.

**Fix:**  
Two new config settings added to `ai/config.py`:

```python
# Default: off. Enable only when context routinely exceeds the LLM's context window.
CONTEXT_COMPRESSION_ENABLED: bool = False   # set to true in .env to enable
# Only compress when total retrieved context exceeds this size.
CONTEXT_COMPRESSION_MIN_CHARS: int = 8000   # was 2 000; ~2 000 tokens at 4 chars/token
```

The guard in `_retrieve_and_build_context()` was updated from:
```python
if not explicit_filename and not is_aggregation and len(documents) >= 2 and total_context_chars >= 2000:
```
to:
```python
if (
    getattr(settings, "CONTEXT_COMPRESSION_ENABLED", False)   # must be explicitly enabled
    and not explicit_filename
    and not is_aggregation
    and len(documents) >= 2
    and total_context_chars >= getattr(settings, "CONTEXT_COMPRESSION_MIN_CHARS", 8000)
):
```

`context_compressor.py` itself is unchanged — it retains its own internal skip-guard as a defensive fallback. Compression is now **opt-in** with a high threshold.

**Verification:** Run a standard 2-document query with default config. Confirm no compression log line appears. Set `CONTEXT_COMPRESSION_ENABLED=true` in `.env` and run a query where context > 8,000 chars. Confirm compression runs.

---

### 4.3 — Lazy Conversation Summarization 🟡 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py` → `build_conversation_history()`  
**File:** `ai/routers/chat.py` → `_build_conversation_history()`

**Problem:**  
`build_conversation_history` was called on every query. Once `len(pairs) > 6`, it always triggered a fresh LLM summarize call for `older_pairs = message_pairs[:-6]`. Between queries within the same turn, `older_pairs` is **identical** — so the same summary was being recomputed from scratch every time, adding a full LLM round-trip to every query in long sessions.

**Fix:**
1. Added `self._summary_cache: Dict[int, Tuple[int, str]]` to the orchestrator `__init__`. The cache maps `session_id → (older_count, summary_text)`, where `older_count = len(older_pairs)`.
2. Updated `build_conversation_history` to accept `session_id: Optional[int] = None`. Before calling the LLM, it checks whether `session_id` is in the cache with the same `older_count`. On a hit, the cached summary is returned immediately. On a miss, the LLM is called and the result is stored (even empty-string failures are cached to avoid retrying every query after a failure).
3. `older_count` only increments when a new exchange pushes another pair out of the verbatim window. Each increment triggers exactly one new summarization call, then future queries reuse the cached text until the next increment.
4. Updated `chat.py`'s `_build_conversation_history` to pass `session_id` to `build_conversation_history`, completing the wiring.

The cache is in-memory on the orchestrator instance (lost on restart), which is intentional — it avoids a DB schema change and is correct: the first long-session query after a restart will regenerate the summary once, then cache it.

**Verification:** In a 15-message session, send 5 back-to-back queries without adding new messages. Confirm the summarization log line (`"Conversation summary generated"`) appears only **once**, and subsequent queries log `"Conversation summary cache hit"` instead.

---

## Phase 5 — Code Quality and Maintainability
**Goal:** Clean up dead code, fix configuration inconsistencies, and add input guards.  
**Status:** [ ] Not Started

---

### 5.1 — Fix `VITE_API_BASE_URL` Being Ignored 🟡 ✅ COMPLETE

**File:** `src/lib/api/client.ts`

**Problem:**  
`src/lib/config.ts` exports `config.api.baseURL` which reads from `VITE_API_BASE_URL` with a localhost fallback. `client.ts` ignored it and hardcoded `http://127.0.0.1:8000/api`. Setting the environment variable had no effect.

**Fix:**  
Replaced the hardcoded string with an import from `$lib/config`:
```typescript
import { config } from '$lib/config';
const apiClient = axios.create({ baseURL: config.api.baseURL, timeout: 60000 });
```
`config.ts` is unchanged — it remains the single source of truth for the base URL.

**Verification:** Set `VITE_API_BASE_URL=http://127.0.0.1:9000/api` in `.env`. Confirm network requests go to port 9000.

---

### 5.2 — Fix `asyncio.create_task()` in Synchronous `__init__` 🟡 ✅ COMPLETE

**File:** `ai/services/document_processor/orchestrator.py` → `__init__()` + new `initialize()`  
**File:** `ai/routers/documents.py` → `set_directory`

**Problem:**  
```python
# in __init__ (synchronous):
asyncio.create_task(self._load_existing_metadata())
asyncio.create_task(self.update_worker.start())
```
Two issues:
1. **Requires a running event loop at construction time.** `__init__` is synchronous. This only worked because FastAPI/uvicorn happened to have an event loop running. Instantiating the orchestrator in a test without an event loop raises `RuntimeError`.
2. **Silent race with `clear_all_data()`.** `asyncio.create_task` schedules the task immediately. In `set_directory`, `clear_all_data()` is awaited right after construction, but the task had already started. `_load_existing_metadata` could begin reading the DB while `clear_all_data` is still wiping it.

**Fix:**  
Removed both `asyncio.create_task` calls from `__init__`. Added `async def initialize()`:
```python
async def initialize(self) -> None:
    asyncio.create_task(self._load_existing_metadata())
    asyncio.create_task(self.update_worker.start())
```
In `documents.py` `set_directory`, `await doc_processor.initialize()` is called **after** the optional `clear_all_data()`:
```python
doc_processor = DocumentProcessorOrchestrator(...)
if not is_resume:
    await doc_processor.clear_all_data()   # DB wiped first
await doc_processor.initialize()           # metadata load now sees clean DB
```
`__init__` is now safe to call from any context, including synchronous test setups.

**Verification:** Instantiate `DocumentProcessorOrchestrator()` in a plain synchronous test (no event loop). Confirm no `RuntimeError`. Separately, confirm startup still loads existing metadata by checking logs for `"metadata loader + update worker started"`.

---

### 5.3 — Add Input Length Validation on Chat Endpoints 🟢

**File:** `ai/schemas/chat.py`  
**File:** `ai/routers/chat.py`

**Problem:**  
`POST /api/chat` and `POST /api/chat/stream` accept `message` strings of arbitrary length. A 100,000-character message will be embedded, fed to the planner LLM, stored in the DB, and counted against Groq's TPM limit without any check.

**Fix:**  
Add a `max_length` validator on `ChatRequest.message`:
```python
from pydantic import field_validator
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[int] = None

    @field_validator("message")
    @classmethod
    def message_not_empty_or_too_long(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        if len(v) > 4000:
            raise ValueError("Message too long (max 4000 characters)")
        return v
```

**Verification:** POST a 5,000-character message. Confirm a 422 Unprocessable Entity response.

---

### 5.4 — Sanitize Exception Messages Returned to Callers 🟢

**File:** `ai/routers/chat.py`, `ai/routers/documents.py`, `ai/routers/system.py`

**Problem:**  
Raw Python exception strings are returned directly in HTTP error responses and in `QueryResult.message` on failure. These can contain file paths, SQL query text, model names, and internal stack details.

**Fix:**  
Define a set of safe error messages for each failure category. Log the full exception server-side. Return only the category message to the caller:
```python
except Exception as e:
    logger.error(f"Query failed: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Query failed. Please try again.")
```

**Verification:** Trigger a deliberate error (e.g., rename the ChromaDB directory). Confirm the API response does not contain the internal path.

---

### 5.5 — Remove Truly Dead Code 🟢 ✅ COMPLETE

**Files touched:**  
- `ai/services/document_processor/retrieval/hybrid_search.py`
- `ai/services/routing/classifier.py`
- `src/lib/config.ts`

**What was found and fixed:**

1. **`analyze_fusion()` → `_analyze_fusion()`** (`hybrid_search.py`)  
   The method had no production callers — one manual test script was the only reference.  
   Renamed to `_analyze_fusion()` to signal it is debug-only tooling. The test (`tests/test_hybrid_search.py`) was updated to match.

2. **Stale "INTERIM" module docstring** (`classifier.py`)  
   The docstring said these heuristics were temporary placeholders "until the planner+tools architecture is in place." The planner HAS been in place since Phase 2.2, and after Phase 4.1 the classifier became a **permanent, zero-cost pre-filter** that runs on every query before the planner. The docstring was rewritten to accurately reflect its two current roles: pre-filter and legacy fallback.

3. **Dead exports removed** (`src/lib/config.ts`)  
   `config.features`, `config.ui`, `isDevelopment`, and `isProduction` were exported but never imported anywhere in the codebase. All four removed. `config.ts` now exports only `config.api` — the single item actually consumed by `client.ts`.

**`router.py` — no change needed.**  
The Router and QueryClassifier are actively used in both `_run_shared_pipeline` (pre-filter) and `_pipeline_legacy` (fallback). Nothing was dead there.

**Verification:** `analyze_fusion` (public) no longer appears in the codebase. `isDevelopment`, `isProduction`, `config.features`, `config.ui` no longer appear outside their former definition file.

---

## Phase 6 — Database and Persistence Hardening
**Goal:** Ensure the database layer is correct and reliable.  
**Status:** [ ] Not Started

---

### 6.1 — Introduce Alembic Migrations 🟠

**File:** `ai/alembic/versions/` (currently empty)  
**File:** `ai/database/database.py` → `create_tables()`

**Problem:**  
`create_tables()` is called on every startup using SQLAlchemy's `create_all()`. This means schema changes silently fail for existing databases — columns added to models do not appear in existing SQLite files without manual intervention. The Alembic setup exists but the `versions/` directory is empty.

**Fix:**  
1. Generate an initial migration: `alembic revision --autogenerate -m "initial"`
2. Replace `create_tables()` startup call with `alembic upgrade head` (can be called from the lifespan as a subprocess or via the Python API).
3. Document this step in the README as a required startup step.

**Verification:** Add a new nullable column to `IndexedDocument`. Run `alembic upgrade head` against an existing database. Confirm the column appears without data loss.

---

### 6.2 — `Settings` Class Type Annotations Are Class-Level, Not Instance-Level 🟢

**File:** `ai/config.py`

**Problem:**  
```python
class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./klair.db")
```
These are class-level attributes. All instances of `Settings` share the same values and mutations via `settings.update()` change the class state. While the current code only creates one instance, this is a latent bug for testing (tests that create multiple `Settings` instances share state).

**Fix:**  
Move all attribute assignments into `__init__`, or use `pydantic.BaseSettings` which handles `.env` loading, type coercion, and instance isolation correctly:
```python
from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./klair.db"
    ...
    model_config = SettingsConfigDict(env_file=".env")
```

**Verification:** In a test, instantiate two `Settings` objects with different env vars. Confirm they have independent values.

---

## Phase 7 — Orchestrator God Object: Decomposition
**Goal:** Address the root architectural problem that was symptomatically treated in Phases 2.2 and 2.3. Break `orchestrator.py` into focused, single-responsibility services.  
**Status:** [ ] Not Started

> **Context:** The original audit identified `orchestrator.py` as a 2,280+ line God Object combining file indexing, directory scanning, retrieval, tool dispatch, agent loop, context compression, conversation history management, statistics, cleanup, and SSE generation. Phase 2.2 eliminated the most acute *symptom* (duplicate query/stream logic), but the root cause remains: one file does too many unrelated things.

---

### 7.1 — Extract `IndexingService` from `orchestrator.py` 🟠 ✅ COMPLETE

**File:** `ai/services/document_processor/indexing_service.py` *(new)*

**Problem:**  
The orchestrator directly handled all aspects of file ingestion (~600 lines) which had nothing to do with query handling.

**Fix:**  
Created `ai/services/document_processor/indexing_service.py` (682 lines) containing:
- `IndexingService` class with `initialize_from_directory`, `_build_metadata_index`, `_index_content_background`, `_process_single_file`, `add_document`, `remove_document`, `enqueue_update`, `cancel_background_work`, `initialize`, `set_post_index_hook`
- `MetadataCache` class (moved from orchestrator)
- `FilenameTrie` is created and owned here; shared with `RetrievalService` via a direct object reference

The orchestrator delegates all indexing calls to `self.indexing`.

---

### 7.2 — Extract `RetrievalService` from `orchestrator.py` 🟠 ✅ COMPLETE

**File:** `ai/services/document_processor/retrieval_service.py` *(new)*

**Problem:**  
Chunk retrieval, reranking, and context assembly were mixed into the orchestrator with no boundary from query dispatch logic.

**Fix:**  
Created `ai/services/document_processor/retrieval_service.py` (616 lines) containing:
- `retrieve_and_build_context(question, query_type, query_embedding) → dict`
- `_retrieve_chunks(...)` — hybrid RRF fusion + reranking
- `get_document_listing(question) → QueryResult`
- `get_all_indexed_docs() → List`
- `_find_explicit_filename` / `_select_relevant_files` helpers

Owns `VectorStoreService`, `BM25Service`, `HybridSearchService`, `ReRankingService`. Receives `filename_trie` by reference from `IndexingService`.

---

### 7.3 — Extract `QueryPipelineService` from `orchestrator.py` 🟡 ✅ COMPLETE

**File:** `ai/services/document_processor/query_pipeline.py` *(new)*

**Problem:**  
The query pipeline (tool loop, planner, legacy classifier, tool layer, conversation summarization) shared the same file as indexing and retrieval — a 2,300-line God Object.

**Fix:**  
Created `ai/services/document_processor/query_pipeline.py` (1,009 lines) containing all pipeline methods. Also added `CONTEXT_CHUNK_SEP` to `query_config.py` as the single source of truth for the chunk separator used by both services.

`orchestrator.py` is now a **thin coordinator** (363 lines): `__init__` wires all services, and every public method is a one-line delegation. All business logic is gone from this file.

**New dependency graph:**
```
IndexingService  ← (VectorStore, BM25, DB, Embedding, Chunker, TextExtractor, FileValidator)
RetrievalService ← (VectorStore, BM25, HybridSearch, Reranker, Embedding, LLM, FilenameTrie*)
QueryPipeline    ← (LLM, Embedding, Router, RetrievalService)
Orchestrator     ← constructs all, exposes stable public API
```
`*` FilenameTrie is the same object instance owned by IndexingService — no synchronisation needed.

---

## Issue Tracking Checklist

| # | Issue | Phase | Severity | Status |
|---|-------|-------|----------|--------|
| 1.1 | BM25 empty after restart | 1 | 🔴 Critical | ✅ Done |
| 1.2 | Quick-hash breaks incremental update | 1 | 🔴 Critical | ✅ Done |
| 1.3 | Query cache never hits (streaming) | 1 | 🔴 Critical | ✅ Done |
| 1.4 | Relevance score ×50 magic multiplier | 1 | 🔴 Critical | ✅ Done |
| 2.1 | RRF fusion built but never used | 2 | 🟠 High | ✅ Done |
| 2.2 | Duplicate query/query_stream logic | 2 | 🟠 High | ✅ Done |
| 2.3 | Remove old boost code after 2.1 | 2 | 🟡 Medium | ✅ Done |
| 3.1 | Chunking by characters not tokens | 3 | 🟠 High | ✅ Done |
| 3.2 | Chunk boundary splits on decimals/abbreviations | 3 | 🟡 Medium | ✅ Done |
| 4.1 | Planner call on every query (incl. greetings) | 4 | 🟡 Medium | ✅ Done |
| 4.2 | Context compression threshold too low | 4 | 🟡 Medium | ✅ Done |
| 4.3 | Conversation summarization on every query | 4 | 🟡 Medium | ✅ Done |
| 5.1 | `VITE_API_BASE_URL` ignored by axios client | 5 | 🟡 Medium | ✅ Done |
| 5.2 | `asyncio.create_task` in `__init__` | 5 | 🟡 Medium | ✅ Done |
| 5.3 | No input length validation on chat | 5 | 🟢 Low | [ ] |
| 5.4 | Exception strings leaked to callers | 5 | 🟢 Low | [ ] |
| 5.5 | Dead code not removed | 5 | 🟢 Low | ✅ Done |
| 6.1 | No Alembic migrations (create_all on startup) | 6 | 🟠 High | [ ] |
| 6.2 | Settings class-level attributes (not instance) | 6 | 🟢 Low | [ ] |
| 7.1 | Orchestrator is a God Object (root cause) | 7 | 🟠 High | ✅ Done |

---

*Last updated: April 15, 2026*
