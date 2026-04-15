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

### 1.2 — Metadata Quick-Hash Breaks Incremental Update Detection 🔴

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

### 1.3 — Query Cache Never Hits (Streaming Path Bypasses It) 🔴

**File:** `ai/routers/chat.py` → `chat_stream()`

**Problem:**  
The query cache is checked and populated only in the non-streaming `POST /api/chat` handler. The frontend always uses `POST /api/chat/stream`. The streaming handler has no cache check at all. Every query goes to the LLM regardless of whether the identical question was just answered.

Additionally, the cache is never invalidated when documents change (new file indexed, file modified), so a cached answer could be stale.

**Fix:**  
1. Add a cache lookup at the top of the `event_generator()` coroutine in `chat_stream`. On a hit, yield the cached `meta`, `token`, and `done` events directly.  
2. Add a cache populate step after `done` is yielded.  
3. Add cache invalidation (clear the session's keys) when a new file is indexed or removed.

**Verification:** Send the same message twice in a streaming session. Confirm the second response is served from cache and does not trigger an LLM call (check logs).

---

### 1.4 — Relevance Score Is Meaningless (Magic ×50 Multiplier) 🔴

**File:** `ai/services/document_processor/orchestrator.py` → `_retrieve_and_build_context()`

**Problem:**  
```python
"relevance_score": round(min(1.0, avg_score * 50), 3),
```
Cosine similarity scores from ChromaDB are on [0, 1]. Multiplying by 50 and clamping to 1.0 means any document with a similarity above 0.02 shows as 100% relevant. All meaningful signal is lost. Users see every source displayed as "highly relevant" regardless of actual quality.

**Fix:**  
Remove the `* 50` multiplier. Return the raw cosine similarity (or a normalized score across the result set) directly. If a 0–100% display is needed in the UI, apply a documented scaling formula that preserves relative differences.

**Verification:** Run a query for content not present in your documents. Confirm source scores are low (< 0.5) rather than 1.0.

---

## Phase 2 — Architecture: Eliminate Dead Code and Fix Hybrid Search
**Goal:** Remove code that was replaced but not deleted, and wire up the actual RRF fusion that was built but never used.  
**Status:** [ ] Not Started

---

### 2.1 — Wire Up `HybridSearchService` RRF Fusion 🟠

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
Replace the manual boost logic in `_retrieve_chunks()` with a call to `self.hybrid_search.fuse_results()`. Convert the ChromaDB result format and the BM25 result format into the `(id, score, metadata)` tuples that `fuse_results()` expects, then rerank the fused list.

**Verification:** Add a document with unique keywords. Query using those exact keywords. Confirm the document appears in results even if it scores low semantically.

---

### 2.2 — Eliminate the Duplicate `query` / `query_stream` Implementation 🟠

**File:** `ai/services/document_processor/orchestrator.py`

**Problem:**  
The following pairs of methods share 90%+ identical logic:
- `query()` and `query_stream()`
- `_query_via_tool_loop()` and `_query_stream_via_tool_loop()`
- `_query_via_planner_fallback()` and `_query_stream_via_planner_fallback()`

Any bug fixed in one is silently still present in the other. Any feature added must be added twice.

**Fix:**  
Refactor the pipeline to always run the non-streaming internal logic, then convert the result to a stream at the outermost layer. The pattern:
1. `_execute_query_pipeline(question, history)` → returns `QueryResult` (all three paths unified here)
2. `query()` → calls pipeline, returns `QueryResult` directly
3. `query_stream()` → calls pipeline, then wraps the result in SSE events

For the token-streaming portion (Groq streaming), extract a helper that accepts a pre-built message list and returns an `AsyncIterator[str]`.

**Verification:** The six methods above should reduce to two (`query` and `query_stream`) plus shared helpers. Confirm identical behavior by running the same query against both endpoints.

---

### 2.3 — Remove `HybridSearchService` Dead Instantiation (After 2.1) 🟡

**File:** `ai/services/document_processor/orchestrator.py`

**Problem:**  
After fixing 2.1 and properly using `HybridSearchService`, confirm the old manual boost code is fully removed. Do not leave both paths in place.

**Fix:**  
Delete the manual boost block (`bm25_hits` set, `boost` calculation, `min(1.0, base_score + boost)` logic) from `_retrieve_chunks()`. Ensure only the RRF path remains.

**Verification:** Search for `bm25_boost` in `orchestrator.py`. It should appear only in configuration, not in retrieval logic.

---

## Phase 3 — Chunking: Character-Count to Token-Count
**Goal:** Make chunking semantically correct and aligned with model constraints.  
**Status:** [ ] Not Started

---

### 3.1 — Switch Chunker to Token-Based Sizing 🟠

**File:** `ai/services/document_processor/extraction/chunker.py`

**Problem:**  
`DocumentChunker` measures chunk size in characters. LLMs and embedding models operate on tokens. The default `CHUNK_SIZE=1000` characters is approximately 250 tokens — very small. The embedding model `BAAI/bge-small-en-v1.5` has a 512-token maximum input. A 250-token chunk is fine for that model, but the relationship between `CHUNK_SIZE` and model capacity is invisible in configuration and will produce surprising behavior if the model is swapped.

**Fix:**  
Introduce a token counter (e.g., using the tokenizer from `sentence-transformers` or `tiktoken`). Measure chunk size in tokens. Update `CHUNK_SIZE` default and documentation to reflect tokens. Add a hard cap at the embedding model's maximum context length (512 for `bge-small-en-v1.5`).

**Verification:** Print token counts for 10 chunks from a sample document. Confirm they fall within the model's token limit.

---

### 3.2 — Fix Chunk Boundary Detection 🟡

**File:** `ai/services/document_processor/extraction/chunker.py` → `_find_chunk_boundary()`

**Problem:**  
The current boundary detection splits on `.!?` followed by whitespace. This incorrectly splits on:
- Decimal numbers: `3.14`, `99.9%`
- URLs: `https://example.com/path`  
- Abbreviations: `e.g.`, `Mr.`, `U.S.A.`
- File paths in document text

**Fix:**  
Use a proper sentence tokenizer such as `nltk.sent_tokenize` or `spacy`'s sentence boundary detection. These handle abbreviations and decimals correctly. For projects that want zero extra dependencies, use a regex that requires the character after the period to be uppercase (indicating a new sentence): `\.\s+[A-Z]`.

**Verification:** Run the chunker on a document containing decimal numbers and abbreviations. Confirm no mid-sentence splits.

---

## Phase 4 — Performance: Reduce LLM Call Count
**Goal:** Cut the number of LLM calls per query without degrading quality.  
**Status:** [ ] Not Started

---

### 4.1 — Eliminate Planner Call for Simple Queries 🟡

**File:** `ai/services/document_processor/orchestrator.py` → `_query_via_planner_fallback()`

**Problem:**  
Every query — including "hello" and "thank you" — goes through a planner LLM call before the actual response. For Ollama users (local), this doubles the minimum latency for every message.

**Fix:**  
Run the `QueryClassifier` (from the legacy routing path) as a fast pre-filter **before** calling the planner. The classifier runs on the LLM but is already present and tuned for this. If it classifies the query as `GREETING` or `GENERAL`, skip the planner entirely and go straight to `_generate_direct_response()`. Only invoke the planner for `DOCUMENT_LISTING` and `DOCUMENT_SEARCH` routes.

**Verification:** Send "hello" to the backend. Confirm only one LLM call is made (the response call), not two.

---

### 4.2 — Gate Context Compression to High-Value Cases Only 🟡

**File:** `ai/services/context_compressor.py`  
**File:** `ai/services/document_processor/orchestrator.py` → `_retrieve_and_build_context()`

**Problem:**  
Context compression runs an extra LLM call for any multi-file query with ≥ 2 documents and ≥ 2,000 characters of context — which is almost every document search query. On the planner path this adds a third LLM call. On a slow local model, this can add 5–15 seconds per query.

**Fix:**  
Raise the thresholds significantly: only compress when context exceeds the provider's context limit (e.g., > 8,000 characters for Ollama, not 2,000). Alternatively, disable compression entirely for Ollama by default and only enable it for Groq/Gemini where it's less of a latency concern. Make it a configuration flag (`CONTEXT_COMPRESSION_ENABLED`) defaulting to `false`.

**Verification:** Run a standard 2-document query. Confirm the log shows no compression LLM call.

---

### 4.3 — Lazy Conversation Summarization 🟡

**File:** `ai/services/document_processor/orchestrator.py` → `build_conversation_history()`

**Problem:**  
The conversation summarization LLM call fires for every query once the session exceeds 6 message pairs (12 messages). For active sessions, this permanently adds a third LLM overhead to every single query.

**Fix:**  
Cache the summary text on the session. Summarize once when the 7th pair is added, then only re-summarize when the "older pairs" window changes (i.e., when a new pair is added and pushes the oldest pair out of the recent window). Store the cached summary in the `ChatSession` DB record or in a per-session in-memory store.

**Verification:** In a 15-message session, confirm the summarization LLM call fires at most once per new message added to the older window, not on every query.

---

## Phase 5 — Code Quality and Maintainability
**Goal:** Clean up dead code, fix configuration inconsistencies, and add input guards.  
**Status:** [ ] Not Started

---

### 5.1 — Fix `VITE_API_BASE_URL` Being Ignored 🟡

**File:** `src/lib/api/client.ts`

**Problem:**  
`src/lib/config.ts` exports `API_BASE_URL` which reads from `VITE_API_BASE_URL` with a localhost fallback. `client.ts` ignores it and hardcodes `http://127.0.0.1:8000/api`. Setting the environment variable has no effect.

**Fix:**  
```typescript
// client.ts
import { API_BASE_URL } from '$lib/config';
const apiClient = axios.create({ baseURL: API_BASE_URL, timeout: 60000 });
```

**Verification:** Set `VITE_API_BASE_URL=http://127.0.0.1:9000/api` in `.env`. Confirm network requests go to port 9000.

---

### 5.2 — Fix `asyncio.create_task()` in Synchronous `__init__` 🟡

**File:** `ai/services/document_processor/orchestrator.py` → `__init__()`

**Problem:**  
```python
asyncio.create_task(self._load_existing_metadata())
asyncio.create_task(self.update_worker.start())
```
These are fire-and-forget tasks in a synchronous constructor. If initialization fails silently, the orchestrator is left in a broken state with no indication. If the orchestrator is ever instantiated in a test outside a running event loop, this raises a `RuntimeError`.

**Fix:**  
Move these calls into an explicit `async def initialize()` method. Call it from `lifespan()` in `main.py` (already an async context) right after `set-directory` creates the orchestrator. Remove them from `__init__`.

**Verification:** Run the existing tests. Confirm no `RuntimeError: no running event loop` appears. Confirm startup still loads existing metadata.

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

### 5.5 — Remove Truly Dead Code 🟢

**Files:**  
- `ai/services/document_processor/retrieval/hybrid_search.py` — `analyze_fusion()` method (only used in tests, if at all; remove or mark private)
- `ai/services/routing/router.py`, `ai/services/routing/classifier.py` — After Phase 2.2, the legacy classifier path becomes a fallback only. Document clearly which methods are "legacy fallback only" with a deprecation comment so they can be removed in a future pass.
- `src/lib/config.ts` — Either delete `API_BASE_URL` (if it becomes genuinely unused after 5.1 is complete on a non-Tauri build) or ensure it's the single source of truth.

**Verification:** Run a full search of the codebase for each removed symbol. Confirm no remaining references.

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

## Issue Tracking Checklist

| # | Issue | Phase | Severity | Status |
|---|-------|-------|----------|--------|
| 1.1 | BM25 empty after restart | 1 | 🔴 Critical | ✅ Done |
| 1.2 | Quick-hash breaks incremental update | 1 | 🔴 Critical | [ ] |
| 1.3 | Query cache never hits (streaming) | 1 | 🔴 Critical | [ ] |
| 1.4 | Relevance score ×50 magic multiplier | 1 | 🔴 Critical | [ ] |
| 2.1 | RRF fusion built but never used | 2 | 🟠 High | [ ] |
| 2.2 | Duplicate query/query_stream logic | 2 | 🟠 High | [ ] |
| 2.3 | Remove old boost code after 2.1 | 2 | 🟡 Medium | [ ] |
| 3.1 | Chunking by characters not tokens | 3 | 🟠 High | [ ] |
| 3.2 | Chunk boundary splits on decimals/URLs | 3 | 🟡 Medium | [ ] |
| 4.1 | Planner call on every query (incl. greetings) | 4 | 🟡 Medium | [ ] |
| 4.2 | Context compression threshold too low | 4 | 🟡 Medium | [ ] |
| 4.3 | Conversation summarization on every query | 4 | 🟡 Medium | [ ] |
| 5.1 | `VITE_API_BASE_URL` ignored by axios client | 5 | 🟡 Medium | [ ] |
| 5.2 | `asyncio.create_task` in `__init__` | 5 | 🟡 Medium | [ ] |
| 5.3 | No input length validation on chat | 5 | 🟢 Low | [ ] |
| 5.4 | Exception strings leaked to callers | 5 | 🟢 Low | [ ] |
| 5.5 | Dead code not removed | 5 | 🟢 Low | [ ] |
| 6.1 | No Alembic migrations (create_all on startup) | 6 | 🟠 High | [ ] |
| 6.2 | Settings class-level attributes (not instance) | 6 | 🟢 Low | [ ] |

---

*Last updated: April 15, 2026*
