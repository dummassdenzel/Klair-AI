# Klair.ai — Full Code Review & Issue Tracker

> Reviewed by: Claude (Professional AI Engineer Advisor)
> Date: 2026-04-21
> Scope: `ai/` directory — full pipeline audit

Status legend: `[ ]` open · `[x]` fixed · `[-]` deferred / won't fix

---

## Philosophy

This review is organized around a simple question: **should we fix this, or replace it?**

Some code has correctness bugs that are worth fixing. Other code is architecturally heading in the wrong direction — it's over-engineered, domain-locked, or reinventing something a battle-tested library already solves better. For a beginner-built codebase, the instinct to build everything custom is natural, but it creates maintenance debt that compounds over time. The sections below are blunt about which parts to drop entirely.

---

## SECTION 1 — DROP AND REPLACE

These are areas where the existing code should be **deleted** and replaced with a better approach. Fixing them incrementally is the wrong move — the design itself is the problem.

---

### DR1. Drop the Entire LLM Layer → Replace With LiteLLM

**Files to delete:** `ai/services/document_processor/llm/llm_service.py`, `ai/services/document_processor/llm/provider_adapters.py`
**Status:** `[ ]`

`llm_service.py` is 700 lines. Every method (`generate_response`, `generate_response_stream`, `generate_simple`, `chat_with_tools`, `chat_messages_stream`) repeats the same `if groq / elif gemini / else ollama` branch three times each. Token usage extraction is copy-pasted verbatim four times. `provider_adapters.py` is a partial attempt at fixing this — it abstracts configuration but not actual API calls, so the if/elif chains remain.

This is a solved problem. [LiteLLM](https://github.com/BerriAI/litellm) is a library that provides a single OpenAI-compatible interface for 100+ providers — Groq, Gemini, Ollama, OpenAI, Anthropic, Mistral, and more. Switching providers becomes a config string:

```python
# Before: 700 lines across 3 provider branches
# After:
from litellm import acompletion

response = await acompletion(
    model="groq/meta-llama/llama-4-scout-17b-16e-instruct",
    # or: "gemini/gemini-2.5-flash"
    # or: "ollama/mistral"
    messages=[{"role": "user", "content": prompt}],
    tools=tools,             # tool calling works identically across all providers
    max_tokens=8192,
    temperature=0.1,
    stream=True,             # streaming works identically too
)
```

**What this unlocks:**
- Tool calling works for ALL providers (Gemini, Ollama, Groq) — same code path
- Streaming works identically — same code path
- Adding a new provider (OpenAI, Anthropic) = change one config string, zero code changes
- LiteLLM handles retry, rate limits, fallbacks, and token counting

**Replacement `LLMService`** shrinks to ~100 lines: holds the model string, delegates to LiteLLM, handles the `_build_prompt` logic.

---

### DR2. Drop the Two-Step Planner Path → One Unified Agent Loop

**Code to delete:**
- `query_pipeline.py`: `_pipeline_planner()`, `_pipeline_legacy()`, `_get_safe_tool_calls_from_classifier()`, `_build_planner_prompt()`, `_parse_planner_output()` (~250 lines)
**Status:** `[ ]`

The planner path exists because Gemini and Ollama were not getting native tool calling. It works by asking the LLM to output a JSON plan (`{"tools": [...]}`), parsing it, executing tools, then calling the LLM again. This is fragile (JSON parse fails regularly), slow (2 full LLM round-trips), and now unnecessary.

Once LiteLLM is in place (DR1), every provider gets native tool calling through the same interface. `_pipeline_tool_loop` becomes the only path. The entire planner subsystem — `_pipeline_planner`, `_pipeline_legacy`, the JSON parser, the fallback classifier — is dead weight.

The routing pre-filters (greeting/listing short-circuits) remain valid and should stay. Only the planner and legacy fallback paths go.

---

### DR3. Drop the Entire `updates/` Pipeline → Simple Hash-Based Re-Index

**Files to delete:** `update_executor.py`, `update_strategy.py`, `chunk_differ.py` (~750 lines)
**Files to keep (but simplify):** `update_queue.py`, `update_worker.py`
**Status:** `[ ]`

This is the most over-engineered part of the entire codebase. The design promises:
- Three strategies: `FULL_REINDEX`, `CHUNK_UPDATE`, `SMART_HYBRID`
- Checkpoint + rollback on failure
- Semantic chunk diffing to identify unchanged chunks

**What it actually does:** look at `_execute_chunk_update` in `update_executor.py`:

```python
# Step 1: Remove removed chunks
for removed_chunk in diff_result.removed_chunks:
    pass  # Will handle in step 3

# Step 2: Update modified chunks
for match in diff_result.modified_chunks:
    pass  # Will handle in step 3

# Step 3: Remove all chunks, then re-add unchanged + modified + added
await self.vector_store.remove_document_chunks(task.file_path)
# ... re-embeds and re-inserts EVERYTHING
```

Steps 1 and 2 are literally `pass`. All three strategies (`FULL_REINDEX`, `CHUNK_UPDATE`, `SMART_HYBRID`) end up doing the exact same thing: delete all chunks for the file and re-insert all new chunks. `SMART_HYBRID` just calls `_execute_chunk_update`.

Meanwhile, `ChunkDiffer` — which this system calls on every file change — runs:
1. O(n×m) text similarity matrix (difflib on every old/new chunk pair)
2. O(n²) greedy matching loop
3. O(n + m) embedding generation for all unmatched chunks
4. Another O(n²) greedy matching loop on embedding similarities

...all to produce a `ChunkDiffResult` that `_execute_chunk_update` completely ignores, because it removes all chunks and re-adds them all anyway.

This is an expensive no-op. On every file save, you pay the cost of a full semantic diff and produce a result that is thrown away.

**Replacement:** 4 lines of logic.
```python
async def handle_file_change(file_path: str):
    old_hash = await db.get_file_hash(file_path)
    new_hash = compute_hash(file_path)
    if old_hash != new_hash:
        await indexing_service.add_document(file_path)  # delete old + re-index
```

The existing `IndexingService.add_document()` already does hash comparison and re-indexing. The entire `updates/` directory is reimplementing something that already exists, worse.

---

### DR4. Drop `currency_totals.py` and `try_aggregate_currency_totals`

**Files to delete:** `ai/services/document_processor/currency_totals.py`
**Code to remove:** `try_aggregate_currency_totals()` in `retrieval_service.py`, the `is_financial_total_aggregate_query()` pre-filter in `query_pipeline.py`
**Status:** `[x]` Fixed

This module extracts PHP/peso amounts from documents using regex and returns `max(amounts)` as the "document total." It exists to answer questions like "what is the total value of all delivery receipts."

Problems:
- `max()` is semantically wrong. A document with line items [PHP 500, PHP 300, PHP 800] and a grand total PHP 1,600 returns PHP 1,600 (correct by luck). A document with two independent transactions PHP 5,000 and PHP 8,000 also returns PHP 8,000 (wrong — real total is PHP 13,000).
- It is exclusively PHP/peso-specific. Any other currency is invisible.
- It is exclusively logistics-domain-specific.
- The LLM already receives the full document text via `retrieve_and_build_context`. It can sum numbers accurately from retrieved context without any of this code.

**Replacement:** Delete it. When a user asks "what is the total value of all delivery receipts?", the existing search pipeline retrieves the relevant chunks and the LLM answers directly. This is what `search_documents` is for. The only reason this module exists is because the planner path (DR2) sometimes failed to call the right tool — a problem that goes away with native tool calling.

---

### DR5. Replace `Settings` Plain Class → Pydantic `BaseSettings`

**File:** `ai/config.py`
**Status:** `[ ]`

```python
class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "...")
```

These are class-level annotations, not instance attributes. `settings.update()` creates instance attributes that shadow the class-level ones — confusing behavior that will bite you. `Settings.CHUNK_SIZE` and `settings.CHUNK_SIZE` return different values after a runtime update.

**Replacement:**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./klair.db"
    CHUNK_SIZE: int = 300
    # ... all other fields

    class Config:
        env_file = ".env"
```

You get: type validation (passing a string where an int is expected raises immediately), automatic `.env` loading, proper instance semantics, IDE autocompletion. Replace `python-dotenv` + manual `os.getenv` with this.

---

## SECTION 2 — FIX (Correctness Bugs)

These are genuine bugs that produce wrong behavior right now.

---

### F1. `_find_explicit_filename` Stem Regex Misdirects Many Queries

**File:** `ai/services/document_processor/retrieval_service.py:654-659`
**Status:** `[ ]`

```python
stem = re.search(r"\b([A-Za-z][A-Za-z0-9_-]{2,})\b", question)
if stem:
    token = stem.group(1)
    if any(c in token for c in "0123456789-_"):
        return token
```

Matches the first word containing a digit or dash. Fires on common natural language:
- `"What happened in Q3-2024?"` → returns `"Q3-2024"` as filename → zero results
- `"How much in Jan-Feb?"` → returns `"Jan-Feb"` → wrong file filter

**Fix:** Delete the stem block. The quoted-name and extension patterns are reliable enough.
**Status:** `[x]` Fixed — stem block deleted from `_find_explicit_filename`.

---

### F2. ChromaDB Collection May Exist With Wrong Distance Metric

**File:** `ai/services/document_processor/storage/vector_store.py:37-42`
**Status:** `[x]` Fixed — warning logged on startup if `hnsw:space != "cosine"`.

`get_or_create_collection` silently ignores `metadata=` on existing collections. Any user whose ChromaDB was created before `"hnsw:space": "cosine"` was added is still on L2 distance. The score formula `1 - dist` is wrong for L2 (distances are unbounded).

**Fix:** On startup, check `self.collection.metadata.get("hnsw:space")` and log a clear warning (or recreate) if it is not `"cosine"`.

---

### F3. `generate_simple` for Gemini Ignores the Computed Token Limit

**File:** `ai/services/document_processor/llm/llm_service.py:537-548`
**Status:** `[ ]` — Resolved by DR1 (LiteLLM)

`out_tokens` is computed (respects `PLANNER_MAX_TOKENS = 600`) but never passed to `generate_content`. The planner call runs with the full 8192-token budget, producing verbose non-JSON output and wasting quota. Fix by passing `generation_config={"max_output_tokens": out_tokens}`. Moot if DR1 is implemented.

---

### F4. ChromaDB Sync Calls Block the Async Event Loop

**File:** `ai/services/document_processor/storage/vector_store.py`
**Status:** `[ ]`

All `async def` methods call the synchronous ChromaDB API directly. `search_similar` is on the hot path of every query — a slow HNSW search (100–500ms) freezes the entire FastAPI server.

**Fix:** Wrap all synchronous ChromaDB calls with `asyncio.to_thread`:
```python
results = await asyncio.to_thread(self.collection.query, ...)
```
Apply to: `search_similar`, `batch_insert_chunks`, `remove_document_chunks`, `get_document_chunks`.

---

### F5. RAG Prompt Is a Single Text Blob Instead of Structured Messages

**File:** `ai/services/document_processor/llm/llm_service.py:640-673`
**Status:** `[ ]` — Resolved by DR1 (LiteLLM)

`_build_prompt` concatenates system instructions, history, context, and question into one string sent as a single `user` message. For Groq and Gemini, which support proper message arrays, this wastes context tokens and makes conversation history less reliable. Fix by using structured messages: system instruction in `role: system`, history as real turns, context in the final user turn. Moot if DR1 is implemented.

---

### F6. `max_chunks_per_file=4` File Diversity Cap Too Tight for Single-File Queries

**File:** `ai/services/document_processor/query_config.py`
**Status:** `[ ]`

At 300 tokens/chunk, 4 chunks = ~1,200 tokens = ~2 pages. For a 10-page document, 80% of content is discarded. The cap serves multi-document breadth but hurts single-document depth. The cap also runs before single-file mode detection, so chunks are discarded and then re-fetched — wasted work.

**Fix:** Only apply the per-file cap when the result set spans multiple files. When `explicit_filename` is set or `len(file_chunks) == 1`, skip it.

---

### F7. Raw DB Queries Bypass `DatabaseService` — See F18

**Status:** `[ ]` — Expanded and consolidated into F18 (six locations total).

Original finding: `RetrievalService` at lines 158-169 imports `AsyncSessionLocal` directly. Additional locations were found during the full review — see F18 for the complete list and fix.

---

### F8. BM25 Index Rebuilt O(n) Times During Initial Indexing

**File:** `ai/services/document_processor/storage/bm25_service.py:98-100`
**Status:** `[ ]`

`add_documents` calls `BM25Okapi(self.tokenized_corpus)` on every invocation — a full O(n) rebuild. For 500 files indexed one-by-one, this is 500 rebuilds = O(n²) total work.

**Fix:** Move the `BM25Okapi(...)` rebuild to an explicit `rebuild()` method. Call it once after batch indexing completes, not inside each `add_documents` call.

---

### F9. BM25 Tokenizer Produces Noise Tokens, No Stop Word Removal

**File:** `ai/services/document_processor/storage/bm25_service.py:74-82`
**Status:** `[ ]`

"BIP-12046" produces tokens `["bip-12046", "bip", "12046"]`. Any query with "bip" now matches every bring-in permit. No stop words are filtered — "the", "is", "a" appear in every document and inflate IDF weights.

**Fix:** Add a minimal English stop word set (20-30 words covers 80% of the problem). Only generate sub-tokens from the extended split when the sub-token is longer than 2 characters.

---

### F10. `_summary_cache` in `QueryPipelineService` Is Unbounded

**File:** `ai/services/document_processor/query_pipeline.py:118`
**Status:** `[ ]`

```python
self._summary_cache: Dict[int, Tuple[int, str]] = {}
```

One entry per session, no eviction. Grows without bound on a long-running server.

**Fix:** Use the same `OrderedDict`-based LRU pattern from `MetadataCache` in `indexing_service.py`. Cap at ~200 sessions.

---

### F11. `VectorStoreService` Has No Thread Lock on Initialization

**File:** `ai/services/document_processor/storage/vector_store.py:19-48`
**Status:** `[ ]`

Unlike `EmbeddingService` which uses `threading.Lock()`, `VectorStoreService._initialize_client()` has no lock. Concurrent startup requests can double-initialize the client.

**Fix:** Add `threading.Lock()` double-check pattern identical to `EmbeddingService._initialize_model()`.

---

### F12. Ollama Non-Streaming Timeout Shorter Than Streaming

**File:** `ai/services/document_processor/llm/llm_service.py:128, 349`
**Status:** `[ ]` — Resolved by DR1 (LiteLLM)

`httpx.AsyncClient` initialized with `timeout=30.0`, but the streaming path uses `timeout=60.0`. Long Ollama generations silently time out at 30s. Both should use `settings.OLLAMA_TIMEOUT` (default 120s). Moot if DR1 is implemented.

---

### F13. `asyncio.get_event_loop()` Deprecated — Use `get_running_loop()`

**Files:** `query_pipeline.py:165,219`; `update_executor.py:103,122`; `indexing_service.py:178,205,209,230,421,424`; `ocr_service.py:364,384`
**Status:** `[ ]`

Deprecated in Python 3.10+, raises in 3.12 in some contexts. Replace all occurrences with `asyncio.get_running_loop()`. For `ocr_service.py`, replace `loop.run_in_executor(None, ...)` with the cleaner `asyncio.to_thread(...)` (Python 3.9+).

---

## SECTION 3 — DEAD CODE TO DELETE

Code that is never called or produces no effect. Delete without replacement.

---

### DC1. `HybridSearchService._analyze_fusion` — Never Called

**File:** `ai/services/document_processor/retrieval/hybrid_search.py:93-130`
**Status:** `[ ]`

~40 lines of fusion analysis logic. Never called anywhere in production. Delete it.

---

### DC2. `VectorStoreService.cleanup()` Does Nothing

**File:** `ai/services/document_processor/storage/vector_store.py:161-169`
**Status:** `[ ]`

Sets references to `None` without calling any close/flush on the ChromaDB client. Either call `self.chroma_client.close()` (if ChromaDB exposes it) or remove the method.

---

### DC3. `_cosine_similarity` in `ChunkDiffer` Is Unused

**File:** `ai/services/document_processor/updates/chunk_differ.py:338-347`
**Status:** `[ ]` — Moot if DR3 implemented

The method exists but is never called — the class uses numpy matrix operations instead. Delete it.

---

### DC5. `get_db()` in `database.py` Is Unused

**File:** `ai/database/database.py:51-56`
**Status:** `[ ]`

```python
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

This FastAPI dependency generator is defined but never injected anywhere — all database access uses `AsyncSessionLocal()` context managers directly. Dead code. Delete it.

---

### DC4. `orchestrator.py` Default Embed Model Is Stale

**File:** `ai/services/document_processor/orchestrator.py:57`
**Status:** `[ ]`

```python
def __init__(self, ..., embed_model_name: str = "BAAI/bge-small-en-v1.5", ...):
```

`config.py` defaults to `"BAAI/bge-base-en-v1.5"`. The orchestrator is always constructed from `settings.to_dict()` in `main.py`, so the config wins in practice. But if anyone constructs `DocumentProcessorOrchestrator()` directly (in tests, or a future CLI), they silently get the smaller, lower-quality model with no warning.

**Fix:** Update the default to `"BAAI/bge-base-en-v1.5"` to match `config.py`.

---

## SECTION 4 — SECURITY

### SEC1. Live API Keys in `.env` — Rotate Immediately

**File:** `ai/.env`
**Status:** `[x]` `.gitignore` confirmed. Rotate keys.

The `.env` file contains plaintext live credentials: Groq API key, Gemini API key, PostgreSQL password. There is also an orphaned bare key on line 15 with no variable assignment. If this repo has ever been pushed to a remote, rotate all three secrets now — bots scan for this pattern within seconds of a push.

**Action:** `.env` is confirmed in `.gitignore`. Rotate Groq key, Gemini key, and PostgreSQL password.

---

### SEC2. `RETRIEVAL_INSPECT_ENABLED=true` in Live Environment

**File:** `ai/.env`
**Status:** `[ ]`

The debug endpoint `POST /api/debug/retrieval-inspect` exposes full retrieved document text and raw RAG prompts to anyone who can reach the API. It is enabled in the live `.env`.

**Fix:** Set `RETRIEVAL_INSPECT_ENABLED=false`. Only enable locally during debugging.

---

## SECTION 5 — DESIGN (Longer-Term)

These are not bugs, but architectural choices worth revisiting as the project matures.

---

### DES1. Domain Hardcoding — Exact Locations Across 4 Files

**Status:** `[x]` Fixed — see changes below each location.

The stated goal is a general-purpose, domain-agnostic folder assistant. The logistics-specific hardcoding below was accumulated during testing against a personal folder of Philippine customs/freight documents. None of it belongs in the codebase. Here is every location, with line references:

#### `ai/services/document_processor/extraction/text_extractor.py`

| Lines | Symbol | What it hardcodes |
|-------|--------|-------------------|
| 14–41 | `_DEFAULT_STANDALONE_DOC_TYPES` | 25 logistics type names: DELIVERY RECEIPT, BRING-IN PERMIT, CARGO GATE PASS, AIRWAY BILL, etc. _Can_ be overridden by taxonomy JSON — but the default is pure logistics. |
| 74 | `_DR_FIELD_RE` | Regex that matches `D.R.#` (Delivery Receipt number) — a field that only exists in Philippines freight documents. |
| 77–82 | `_DR_SUPPORTING_SIGNAL_RE` | Regex matching "DELIVER TO", "CONSIGNEE", "DELIVERED BY" — logistics fields. |
| 84–91 | `_RELAXED_BIP_LINE` / `_RELAXED_BOP_LINE` | Regex patterns for Bring-In Permit and Bring-Out Permit line formats — specific document sub-types. |
| 100 | `_BIP_FILENAME_STEM_RE` | Matches filenames starting with `BIP-` — a specific permit filename convention. |
| 172–227 | `extract_doc_title` passes 4–6 | Passes 1–3 use `STANDALONE_DOC_TYPES` (JSON-configurable). **Passes 4–6 are not config-driven at all:** pass 4 checks for `BIP-` filename stem, pass 5 checks for "BRING-IN PERMIT" in the document body, pass 6 checks for `D.R.#` + a delivery-party field. A research paper, code repo, or financial report will never match any of these — but the code still runs these checks on every document, every time. |

#### `ai/services/document_processor/retrieval_service.py`

| Lines | Symbol | What it hardcodes |
|-------|--------|-------------------|
| 40–102 | `_match_category_listing_intent` | 60-line chain of regex → frozenset mappings for 10 logistics document types (DELIVERY RECEIPT, BRING-IN PERMIT, CARGO GATE PASS, etc.). When the user asks "list all delivery receipts", this function routes the query. Works perfectly on logistics — routes every other domain's query to "unknown". NOT loaded from taxonomy JSON. |

#### `ai/services/document_processor/query_pipeline.py`

| Lines | Symbol | What it hardcodes |
|-------|--------|-------------------|
| ~125–145 | `AGENT_SYSTEM_MESSAGE` | Contains explicit logistics instructions: "When working with delivery receipts, bring-in permits, cargo gate passes..." and references to `D.R.#` fields. Every query from every user on every folder type gets a system prompt written for a Philippine freight forwarder. |
| `_build_planner_prompt` | (planner path) | Contains logistics-specific few-shot examples. Moot if DR2 is implemented. |

#### `ai/services/document_processor/query_config.py`

| Lines | Symbol | What it hardcodes |
|-------|--------|-------------------|
| 51–56 | `is_financial_total_aggregate_query` | Regex includes `r"\b(php\|peso\|pesos)\b"` — currency terms specific to the Philippine peso. Any folder not containing PHP amounts will never trigger this path, and any non-PHP currency user gets no financial aggregation support. |

#### `ai/services/document_processor/tools/contract.py`

| Lines | Symbol | What it hardcodes |
|-------|--------|-------------------|
| 105, 109 | `TOOL_SEARCH_SPECIFIC_DOCUMENT` description and `document_name` parameter description | Uses `BIP-12046` as the example identifier in the tool description exposed to the LLM. The LLM sees this as a model example and is nudged toward expecting BIP-style filenames. |

#### `ai/services/document_processor/currency_totals.py`

Entire file (DR4). PHP/peso-specific regex, `max(amounts)` semantics. See DR4.

---

**Fix strategy, in order:**
1. Delete `_DR_FIELD_RE`, `_DR_SUPPORTING_SIGNAL_RE`, `_RELAXED_BIP_LINE`, `_RELAXED_BOP_LINE`, `_BIP_FILENAME_STEM_RE` from `text_extractor.py`. Remove passes 4–6 from `extract_doc_title`.
2. Replace `_match_category_listing_intent` with a lookup table loaded from `resources/document_category_taxonomy.json` at startup. Ship an empty or minimal default taxonomy — users configure it for their domain.
3. Replace `AGENT_SYSTEM_MESSAGE` with a generic system prompt: "You are a helpful assistant that answers questions about the user's documents. Answer based only on the provided context."
4. Delete `currency_totals.py` (DR4).

After these changes, the pipeline is domain-agnostic by default. The taxonomy JSON becomes the single place where any domain customization lives.

---

---

## SECTION 6 — BUGS FOUND IN REMAINING FILES

These were identified during review of `text_extractor.py`, `database/`, `routers/documents.py`, and `main.py`. They are separate from the issues above.

---

### F14. `_extract_docx` Misses All Word Table Content

**File:** `ai/services/document_processor/extraction/text_extractor.py:492-500`
**Status:** `[x]` Fixed — `_extract_docx` now iterates `doc.tables` after paragraphs.

```python
return "\n".join([para.text for para in doc.paragraphs])
```

`doc.paragraphs` only yields paragraph-level text nodes. Word tables (`doc.tables`) are completely skipped. For any `.docx` that has data in tables — purchase orders, invoices, schedules, price lists — the extracted text is empty or nearly empty, which means nothing relevant gets indexed.

**Fix:**
```python
from docx.oxml.ns import qn

parts = [para.text for para in doc.paragraphs]
for table in doc.tables:
    for row in table.rows:
        parts.append("\t".join(cell.text for cell in row.cells))
return "\n".join(parts)
```

---

### F15. Deprecated `datetime.utcnow()` and Naive Datetimes Throughout the Codebase

**Files:** `ai/database/models.py`, `ai/database/service.py`, `ai/services/document_processor/updates/update_queue.py:46`, `ai/services/document_processor/extraction/file_validator.py:86-88`
**Status:** `[ ]`

`datetime.utcnow()` is deprecated in Python 3.12 and returns a naive (timezone-unaware) datetime. `datetime.fromtimestamp(mtime)` in `file_validator.py` also returns a naive local-time datetime (not UTC) — so stored `last_modified` timestamps are in the server's local timezone, not UTC, which produces wrong comparisons when the server is not in UTC.

**Fix:** Replace all occurrences:
- `datetime.utcnow()` → `datetime.now(timezone.utc)`
- `datetime.fromtimestamp(ts)` → `datetime.fromtimestamp(ts, tz=timezone.utc)`
- Dataclass defaults: `field(default_factory=datetime.utcnow)` → `field(default_factory=lambda: datetime.now(timezone.utc))`

---

### F16. `get_chat_sessions_by_directory` Loads All Sessions Into Memory

**File:** `ai/database/service.py`
**Status:** `[ ]`

The method executes `SELECT * FROM chat_sessions` (no WHERE clause), loads every session across every directory into Python memory, then filters with a list comprehension. On a long-running install with hundreds of sessions, this is an O(n) memory scan for what should be a single indexed lookup.

**Fix:** Add `WHERE directory_path = :path` to the query. Add a database index on `chat_sessions.directory_path`.

---

### F17. `search_documents` Uses `LIKE '%value%'` — Full Table Scan

**File:** `ai/database/service.py`
**Status:** `[ ]`

```python
func.lower(IndexedDocument.filename).contains(value)
```

SQLAlchemy `.contains()` generates `LIKE '%value%'`. SQLite cannot use a B-tree index for a leading-wildcard LIKE — every row is scanned. On a directory with thousands of indexed files this is slow and will get worse.

**Fix (short term):** Use `LIKE 'value%'` (trailing wildcard only) when possible, and add an index on `filename`. **Fix (proper):** Add a [SQLite FTS5](https://www.sqlite.org/fts5.html) virtual table (`CREATE VIRTUAL TABLE doc_fts USING fts5(filename, content='indexed_documents')`) and query it for full-text search.

---

### F18. Raw DB Queries Bypass `DatabaseService` in Six Locations

**Files:** `ai/routers/documents.py`, `ai/services/document_processor/retrieval_service.py:158-169`, `ai/services/document_processor/updates/update_executor.py:183-198,479-487`, `ai/services/document_processor/indexing_service.py:514-522,664-698`, `ai/services/document_processor/orchestrator.py:289-302`
**Status:** `[ ]`

Six separate places in the codebase import `AsyncSessionLocal` + `IndexedDocument` directly and write inline SQLAlchemy queries, bypassing `DatabaseService`. This means any schema change (new column, rename, soft-delete flag) must be found and updated in six independent locations. The router, the indexer, the retriever, the update executor, and the orchestrator each maintain their own notion of what an `IndexedDocument` looks like.

The pattern appears as:
```python
from database.database import AsyncSessionLocal
from database.models import IndexedDocument
from sqlalchemy import select
async with AsyncSessionLocal() as db_session:
    stmt = select(IndexedDocument).where(...)
```

**Fix:** Every query against `IndexedDocument` goes through `DatabaseService`. Add `get_document_by_path`, `delete_all_documents`, `get_all_indexed_docs` to `DatabaseService`. No raw session imports outside of `database/`.

---

### F19. `_extract_xlsx` and `_extract_xls` in `text_extractor.py` Are Now Dead Code

**File:** `ai/services/document_processor/extraction/text_extractor.py`
**Status:** `[ ]`

`indexing_service.py` routes all spreadsheet files through `SpreadsheetExtractor.extract_chunks()` before calling `text_extractor.extract_text_async()` at all — `.xlsx` and `.xls` files never reach the text extractor. The `_extract_xlsx` / `_extract_xls` / `_extract_sheet_content` / `_extract_xls_sheet_content` methods in `text_extractor.py` are unreachable.

**Fix:** Delete these four methods from `text_extractor.py`. The `SpreadsheetExtractor` is the authoritative path for spreadsheets.

---

### F20. `_prewarm_services` Warms the Wrong `EmbeddingService` Instance

**File:** `ai/main.py`
**Status:** `[ ]`

```python
async def _prewarm_services():
    svc = EmbeddingService(settings.EMBED_MODEL_NAME)
    svc._initialize_model()   # downloads & caches weights on disk
    del svc
```

This downloads the HuggingFace model weights to disk cache, which is useful. But it creates and then immediately discards an `EmbeddingService` instance. The actual `EmbeddingService` used by the orchestrator is created later, inside `set_directory`. The orchestrator's instance must still lazy-load the model on the first real query — the warmup only saves the network download, not the load-into-memory step.

**Fix:** Expose the `EmbeddingService` singleton on `AppState` at startup. `_prewarm_services` initializes it once. `set_directory` reuses the same instance rather than creating a new one.

---

### F21. `debug_retrieval.py` Calls Unimported Function — Live `NameError`

**File:** `ai/routers/debug_retrieval.py:82`
**Status:** `[ ]`

```python
rewritten = rewrite_with_last_document(raw_message, None)
```

`rewrite_with_last_document` is never imported in this file. The imports bring in `_rewrite_query_for_session` from `.chat`, but not `rewrite_with_last_document` from `services.query_rewriter`. Any request to `POST /api/debug/retrieval-inspect` where `session_id` is `None` raises `NameError` immediately.

**Fix:** Add `from services.query_rewriter import rewrite_with_last_document` to the imports.
**Status:** `[x]` Fixed — import added to `debug_retrieval.py`.

---

### F23. `calculate_file_hash` Blocks the Async Event Loop for Large Files

**File:** `ai/services/document_processor/extraction/file_validator.py:61-72`, called from `ai/services/document_processor/indexing_service.py:490,506`
**Status:** `[ ]`

```python
current_hash = self.file_validator.calculate_file_hash(file_path)
```

`calculate_file_hash` opens and reads the file in 64KB chunks using standard synchronous `open()`. It is called directly (no `asyncio.to_thread`) inside `async def add_document`. For a 50MB file (the configured maximum), this reads ~800 chunks synchronously, blocking the FastAPI event loop for the duration. During initial indexing with `asyncio.gather` over a full batch, every file in the batch blocks in turn.

**Fix:** Wrap the call with `asyncio.to_thread`:
```python
current_hash = await asyncio.to_thread(self.file_validator.calculate_file_hash, file_path)
```

---

### F22. Two Separate `DatabaseService` Instances — Diverging Connection Pools

**Files:** `ai/dependencies.py:9`, `ai/services/document_processor/orchestrator.py:105`
**Status:** `[ ]`

```python
# dependencies.py
db_service = DatabaseService()   # used by all routers

# orchestrator.py
self.database_service = DatabaseService()  # used by the pipeline
```

Two completely separate `DatabaseService` instances run against the same SQLite file. Correctness is maintained (SQLite serializes writes), but any caching, counters, or future state inside `DatabaseService` will split across two instances. When connection pooling is added or DR5 is implemented, this becomes a real problem.

**Fix:** Pass `db_service` from `dependencies.py` into the orchestrator at construction time in `main.py` so the whole application shares one instance.

---

### DES2. No Retry Logic for LLM API Failures

**Files:** `llm_service.py` throughout (resolved in DR1 if using LiteLLM)
**Status:** `[ ]`

A Groq 429 (rate limit) or Gemini 503 returns "I couldn't generate a response." immediately. LiteLLM has built-in retry support. If staying on custom code, wrap calls with `tenacity` exponential backoff for transient errors (429, 503, timeout).

---

### DES3. BGE Embedding Model Is English-Only

**File:** `ai/config.py:22`
**Status:** `[ ]`

`BAAI/bge-base-en-v1.5` is English-only. Filipino, Tagalog, or mixed-language documents (common in a Philippine logistics context) will produce degraded embeddings and poor retrieval.

**Consider:** `BAAI/bge-m3` (multilingual, same asymmetric prefix convention, same API) or `intfloat/multilingual-e5-base`. Both are drop-in replacements — same `encode_texts()`/`encode_query()` call sites, same BGE prefix behavior.

---

### DES4. `query_rewriter.py` Uses 2-Space Indentation

**File:** `ai/services/query_rewriter.py`
**Status:** `[ ]`

Every other file in the project uses 4-space indentation. This file uses 2-space throughout. Fix for consistency.

---

### DES5. Token Usage Tracking Is In-Memory Only

**File:** `ai/services/document_processor/llm/llm_service.py:44-46`
**Status:** `[ ]`

Cumulative token counters reset on every restart. If you care about cost tracking, this data needs to be persisted to the database. LiteLLM (DR1) provides accurate per-call token counts that can be logged directly.

---

### DES6. `[Region: full/left/right]` Markers Flow Into Embedded Chunks

**File:** `ai/services/document_processor/extraction/text_extractor.py` (PDF extraction path)
**Status:** `[ ]`

The PDF column-detection logic prefixes extracted text with `[Region: full]`, `[Region: left]`, `[Region: right]` to indicate page layout. These markers flow directly into chunks and get embedded. The embedding model has never seen these markers in training — they are invisible noise that slightly degrades vector representations and wastes token budget.

**Fix:** Strip `[Region: ...]` markers in the chunker (or before the embedding call in `EmbeddingService`) rather than persisting them into stored chunk text. They are only useful for human debugging, not for retrieval.

---

## Summary Table

| ID | Category | Severity | Description | Status |
|----|----------|----------|-------------|--------|
| DR1 | Drop & Replace | Critical | Drop LLM layer → LiteLLM | `[ ]` |
| DR2 | Drop & Replace | High | Drop planner path (~250 lines) | `[ ]` |
| DR3 | Drop & Replace | High | Drop updates pipeline → simple re-index | `[ ]` |
| DR4 | Drop & Replace | Medium | Drop `currency_totals.py` | `[x]` Fixed |
| DR5 | Drop & Replace | Medium | Drop `Settings` class → Pydantic `BaseSettings` | `[ ]` |
| F1 | Fix | Critical | Filename stem regex misdirects queries | `[x]` Fixed |
| F2 | Fix | Critical | ChromaDB distance metric not verified on startup | `[x]` Fixed |
| F3 | Fix | Critical | Gemini `generate_simple` ignores token cap | `[ ]` |
| F4 | Fix | High | ChromaDB sync calls block event loop | `[x]` Fixed |
| F5 | Fix | High | RAG prompt is single text blob, not messages | `[ ]` |
| F6 | Fix | High | `max_chunks_per_file=4` too tight | `[x]` Fixed |
| F7 | Fix | High | `RetrievalService` bypasses `DatabaseService` | `[ ]` |
| F8 | Fix | Medium | BM25 O(n²) rebuild during indexing | `[x]` Fixed |
| F9 | Fix | Medium | BM25 noise tokens, no stop words | `[x]` Fixed |
| F10 | Fix | Medium | Unbounded `_summary_cache` | `[x]` Fixed |
| F11 | Fix | Low | No thread lock on `VectorStoreService` init | `[x]` Fixed (part of F4) |
| F12 | Fix | Low | Ollama timeout inconsistency | `[ ]` |
| F13 | Fix | Low | Deprecated `asyncio.get_event_loop()` | `[x]` Fixed |
| F14 | Fix | Critical | `_extract_docx` skips all Word table content | `[x]` Fixed |
| F15 | Fix | Medium | `datetime.utcnow()` deprecated throughout DB layer | `[x]` Fixed |
| F16 | Fix | Medium | `get_chat_sessions_by_directory` full table scan | `[x]` Fixed |
| F17 | Fix | Medium | `search_documents` uses `LIKE '%val%'` — no index | `[ ]` requires FTS5 migration |
| F18 | Fix | Medium | Router endpoints bypass `DatabaseService` | `[ ]` |
| F19 | Fix | Low | `_extract_xlsx` / `_extract_xls` dead code deleted | `[x]` Fixed |
| F20 | Fix | Low | `_prewarm_services` warms a throwaway instance | `[ ]` |
| F21 | Fix | High | `debug_retrieval.py` missing import — live `NameError` | `[x]` Fixed |
| F22 | Fix | Medium | Two separate `DatabaseService` instances application-wide | `[x]` Fixed |
| F23 | Fix | Medium | `calculate_file_hash` blocks async event loop for large files | `[x]` Fixed |
| DC1 | Dead Code | Low | `_analyze_fusion` never called | `[x]` Fixed |
| DC2 | Dead Code | Low | `VectorStoreService.cleanup()` does nothing | `[x]` Fixed |
| DC3 | Dead Code | Low | `_cosine_similarity` in `ChunkDiffer` unused | `[x]` Fixed |
| DC4 | Dead Code | Low | Stale default embed model in `orchestrator.py` | `[x]` Fixed |
| DC5 | Dead Code | Low | `get_db()` generator in `database.py` never called | `[x]` Fixed |
| SEC1 | Security | Critical | Live API keys in `.env` | `[x]` .gitignore confirmed |
| SEC2 | Security | High | Debug endpoint enabled in live env | `[ ]` |
| DES1 | Design | Critical | Logistics hardcoding in 4 files — exact locations documented | `[x]` Fixed |
| DES2 | Design | Medium | No retry on LLM API failures | `[ ]` |
| DES3 | Design | Medium | English-only embedding model | `[ ]` |
| DES4 | Design | Low | `query_rewriter.py` wrong indentation | `[x]` Fixed |
| DES5 | Design | Low | Token tracking in-memory only | `[ ]` |
| DES6 | Design | Low | `[Region:]` markers embedded into chunk text | `[x]` Fixed |

### What to tackle first (recommended order)

1. **SEC1** — Rotate API keys. Do this today.
2. **DES1** — Strip the logistics hardcoding. This is what makes the app domain-agnostic. Most deletions are < 10 lines each.
3. **F14** — Add `doc.tables` to `_extract_docx`. One-hour fix that unlocks Word table content for all users.
4. **DR1 (LiteLLM)** — This unblocks DR2 and resolves F3, F5, F12 for free. The biggest leverage item.
5. **F1** — One-line fix. Immediately improves query quality.
6. **F2** — Verify ChromaDB distance metric. One startup check.
7. **DR3** — Delete ~750 lines of updates pipeline. Replace with 4 lines.
8. **F4** — Wrap ChromaDB calls in `asyncio.to_thread`. Fixes server freezes.
9. **DR2** — After DR1, delete the planner path. ~250 lines gone.
10. **F6 + F16 + F17** — Tune retrieval config and add DB indexes. Improves answer depth and query speed.
