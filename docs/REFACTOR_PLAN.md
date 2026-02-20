# Klair.ai Refactor Plan

> **Goal:** Transform Klair.ai from an over-engineered cloud SaaS codebase into a lean,
> fast, token-efficient local-first AI document workspace — aligned with the Claude Cowork
> model of "select a folder, ask about it."
>
> **Guiding principles:**
> - Every LLM call must earn its keep. If heuristics can do it, don't burn tokens.
> - A desktop app has one user. Remove anything that exists to serve multiple.
> - Fewer lines = fewer bugs = faster iteration. Delete aggressively.
> - Ship the core loop first: select folder → index → chat. Everything else is polish.

---

## Phase 1 — Foundation: Make It a Real Desktop App

**Why first:** These are architectural blockers. PostgreSQL prevents distribution. Tkinter
breaks Tauri. Multi-tenancy and rate limiting add complexity to every future change. Nothing
else matters until the foundation is right.

**Estimated effort:** 2–3 days

### 1.1 Replace PostgreSQL with SQLite

| Item | Detail |
|------|--------|
| **Problem** | Users must install and run a PostgreSQL server to use a local desktop app. |
| **Solution** | Switch to SQLite via `aiosqlite` + SQLAlchemy async. Single-file DB, zero setup. |
| **What changes** | `database/database.py` connection string, Alembic config, remove `asyncpg`/`psycopg2-binary` from requirements. All SQLAlchemy models and queries stay the same. |
| **Risk** | SQLite has limited concurrent write throughput. Irrelevant for a single-user desktop app. |

Steps:
- [ ] Install `aiosqlite` dependency
- [ ] Change `DATABASE_URL` default to `sqlite+aiosqlite:///./klair.db`
- [ ] Update `database/database.py` engine creation (remove PostgreSQL-specific flags)
- [ ] Update Alembic `env.py` for SQLite dialect
- [ ] Generate a fresh initial migration against SQLite
- [ ] Remove `asyncpg` and `psycopg2-binary` from `requirements.txt`
- [ ] Test all DB operations (CRUD, window functions, JSON columns)

### 1.2 Remove Multi-Tenancy (TenantRegistry)

| Item | Detail |
|------|--------|
| **Problem** | ~200 lines of LRU eviction, tenant headers, per-tenant isolation for a single-user app. Every endpoint carries tenant resolution overhead. |
| **Solution** | Replace with a simple module-level singleton: one `DocumentProcessorOrchestrator`, one `FileMonitorService`, one `current_directory`. |
| **What changes** | Delete `tenant_registry.py`. Simplify every endpoint that currently calls `Depends(require_tenant_context)`. |

Steps:
- [x] Create a simple `AppState` dataclass holding `doc_processor`, `file_monitor`, `current_directory`
- [x] Store it on `app.state` directly (no registry, no LRU, no headers)
- [x] Update all endpoints to read from `app.state` instead of tenant context
- [x] Remove `X-Tenant-ID` header logic from frontend API client (confirmed: none existed)
- [x] Delete `tenant_registry.py`
- [x] Remove `get_tenant_persist_dir` — use a single `chroma_db/` directory
- [x] Update `query_cache.py` to remove tenant_id from cache key
- [x] Delete `tests/test_tenant_registry.py`
- [x] Update `tests/test_query_cache.py` for new signature

### 1.3 Remove Rate Limiting

| Item | Detail |
|------|--------|
| **Problem** | `slowapi` rate-limits the only user of the app. Actively harmful UX during heavy use. |
| **Solution** | Delete all `slowapi` references. |

Steps:
- [x] Remove `slowapi` imports, middleware, exception handler from `main.py`
- [x] Remove `@limiter.limit(...)` decorators from all endpoints (5 total)
- [x] Remove `slowapi` from `requirements.txt`

### 1.4 Use Tauri Native Dialog Instead of tkinter

| Item | Detail |
|------|--------|
| **Problem** | The Python backend opens a tkinter GUI dialog to pick a directory. Breaks on headless systems, creates threading issues, wrong architecture layer. |
| **Solution** | Use `@tauri-apps/plugin-dialog` on the frontend. Send the selected path to `/api/set-directory`. |

Steps:
- [x] Install `@tauri-apps/plugin-dialog` in the Tauri frontend (JS + Rust + capabilities)
- [x] Rewrite `DirectorySelectionModal.svelte` to use Tauri native dialog (`open()`)
- [x] Remove `selectDirectory()` from `services.ts`
- [x] Remove the `/api/select-directory` endpoint entirely from `main.py`
- [x] Remove `tkinter` usage and unused `BASE_SUPPORTED_EXTENSIONS` import from backend

---

## Phase 2 — Token Diet: Stop Wasting LLM Calls

**Why second:** After Phase 1 makes the app distributable, this is the highest-ROI work.
Every saved LLM call reduces cost, latency, and API dependency. These changes compound —
saving 2–3 calls per user message adds up to thousands of saved calls per day of usage.

**Estimated effort:** 1–2 days

### 2.1 Replace LLM-Based Query Classification with Heuristics

| Item | Detail |
|------|--------|
| **Problem** | Every user message makes a ~300-token LLM call just to classify it into one of 4 categories (greeting / general / listing / search). This is the single largest token waste. |
| **Solution** | A heuristic classifier using keyword matching and simple patterns. Covers 95%+ of cases. Fall back to `document_search` when uncertain (safest default). |
| **Token savings** | ~300 tokens per query × every query = massive. |

Steps:
- [x] Rewrite `QueryClassifier.classify()` as a pure heuristic function (no LLM)
- [x] Keep the fast-path greeting detection, expand it (multi-word greetings, "hey there", etc.)
- [x] Add regex patterns for `general` ("what can you do", "how does this work", "help", etc.)
- [x] Add regex patterns for `document_listing` with `$`-anchored boundaries to avoid matching filtered subsets
- [x] Default everything else to `document_search`
- [x] Remove `generate_simple` call from the classifier
- [x] Remove classification cache (no longer needed — classification is instant)
- [x] Delete the LLM-based classification prompt entirely
- [x] Verified 22/22 test cases pass (greetings, general, listing, search, edge cases)

### 2.2 Remove LLM Document Type Classification During Indexing

| Item | Detail |
|------|--------|
| **Problem** | Every file makes an LLM call to classify its "document category" (invoice, permit, etc.) during indexing. 100 files = 100 extra API calls. |
| **Solution** | Remove `classify_document_type()` calls during indexing. If category filtering is needed later, do it at query time or use simple file-extension / content heuristics. |
| **Token savings** | ~200 tokens per file × number of files in directory. |

Steps:
- [x] Remove `classify_document_type()` call from `add_document()` in orchestrator
- [x] Remove `document_category` from the indexing pipeline (keep the DB column for future use)
- [x] Remove `_get_requested_categories_for_query()` LLM call from query pipeline
- [x] Remove `document_category_filter` logic from `_retrieve_chunks()` (simplify retrieval)
- [x] Delete `classify_document_type()` from `llm_service.py`
- [x] Remove `document_classifier` from `UpdateExecutor` (constructor + all usage)
- [x] Remove `document_category` param from `vector_store.batch_insert_chunks()`
- [x] Delete `get_file_paths_by_category()` and `get_distinct_document_categories()` from DB service
- [x] Keep the `document_category` DB column — can be populated later by cheaper means

### 2.3 Remove Pre-Warming LLM Call

| Item | Detail |
|------|--------|
| **Problem** | On startup, creates a throwaway orchestrator and makes a real LLM API call ("Hello" + test context). For cloud APIs (Groq/Gemini), there's nothing to warm up. Wastes tokens. |
| **Solution** | Keep embedding model warm-up only (load the model into memory). Remove the LLM call. |

Steps:
- [x] Remove the LLM `generate_response` call from `prewarm_services()`
- [x] Remove the temporary `DocumentProcessorOrchestrator` creation
- [x] Keep only the embedding model load (direct `EmbeddingService` instantiation)
- [x] Simplified `prewarm_services()` from ~40 lines to 6 lines
- [x] Removed unused `prewarming_complete` global flag

### 2.4 Optimize the RAG Prompt

| Item | Detail |
|------|--------|
| **Problem** | The system prompt in `_build_prompt()` is ~400 tokens of instructions. Many instructions are redundant or overly specific. |
| **Solution** | Trim to essentials. The model already knows how to answer questions from context. |

Steps:
- [x] Reduce `_build_prompt()` instruction section from 12 bullet points to 4
- [x] Remove domain-specific instructions (invoices, permits, receipts, totals/sums, scope by type)
- [x] Keep only: answer from context, cite documents, combine chunks, say "I don't know"
- [ ] Test quality — a shorter prompt often performs equally or better

---

## Phase 3 — Code Cleanup: Eliminate Duplication and Bloat

**Why third:** With the foundation fixed and tokens saved, now clean up the codebase so
future changes are fast and safe. This phase is about developer velocity.

**Estimated effort:** 2–3 days

### 3.1 Extract Shared Retrieval Logic from query() and query_stream()

| Item | Detail |
|------|--------|
| **Problem** | `query()` and `query_stream()` are ~200 lines each with nearly identical retrieval, context building, and source assembly logic — copy-pasted. |
| **Solution** | Extract a `_retrieve_and_build_context()` method. Both methods call it, then diverge only at response generation (batch vs stream). |

Steps:
- [x] Create `_retrieve_and_build_context(question, query_type, query_embedding)` → returns dict with context, sources, retrieval_count, rerank_count (or None)
- [x] Refactor `query()` to call it then `generate_response()`
- [x] Refactor `query_stream()` to call it then `generate_response_stream()`
- [x] Delete all duplicated retrieval/context code
- [x] Reduction: **112 lines** (1374 → 1262)

### 3.2 Split main.py into FastAPI Routers

| Item | Detail |
|------|--------|
| **Problem** | `main.py` is 1529 lines with all routes inline. Impossible to navigate. |
| **Solution** | Split into `routers/` with separate files per domain. |

Target structure:
```
ai/
  routers/
    chat.py          # /api/chat, /api/chat/stream, /api/chat-sessions/*
    documents.py     # /api/documents/*, /api/set-directory, /api/clear-index
    system.py        # /api/status, /api/configuration
  main.py            # App creation, middleware, lifespan — ~50 lines
```

Steps:
- [x] Create `ai/routers/` directory and `ai/dependencies.py` (shared singletons)
- [x] Move chat + session endpoints to `routers/chat.py` (302 lines)
- [x] Move document/directory/pptx/update endpoints to `routers/documents.py` (470 lines)
- [x] Move status/config/metrics/analytics endpoints to `routers/system.py` (211 lines)
- [x] Wire routers into `main.py` with `app.include_router()`
- [x] `main.py` reduced from **1381 → 93 lines**

### 3.3 Deduplicate document-chat linking logic

| Item | Detail |
|------|--------|
| **Problem** | `link_one_source` / `link_one` is defined twice inline in `/api/chat` and `/api/chat/stream`. |
| **Solution** | Move to `DatabaseService.link_sources_to_chat(sources, session_id)`. |

Steps:
- [ ] Add `link_sources_to_chat()` method to `DatabaseService`
- [ ] Replace both inline functions with a single call
- [ ] Delete the duplicated inline functions

### 3.4 Unify Configuration

| Item | Detail |
|------|--------|
| **Problem** | Config is split across `config.py` (Settings), `document_processor/__init__.py` (config), and `query_config.py` (RetrievalConfig). Unclear source of truth. |
| **Solution** | Single `config.py` with all settings. Other modules import from it. |

Steps:
- [ ] Move document processor config values into `Settings` class in `config.py`
- [ ] Move retrieval config values into `Settings` or keep as a sub-config imported from `config.py`
- [ ] Remove the separate `config` object from `document_processor/__init__.py`
- [ ] Update all imports

### 3.5 Fix Miscellaneous Code Quality Issues

- [ ] Replace all `datetime.utcnow()` with `datetime.now(datetime.UTC)`
- [ ] Replace `print()` in `database/service.py` with `logger.error()`
- [ ] Remove bare `except:` (line 686–687 in orchestrator)
- [ ] Remove `# NEW:` comments throughout (these are not "new" anymore)
- [ ] Remove emoji from log messages (use structured logging fields instead)

---

## Phase 4 — Dependency Diet: Shrink the Footprint

**Why fourth:** After the code is clean, reduce the install/bundle size. A desktop app
that requires 3GB of Python ML dependencies won't get adopted.

**Estimated effort:** 2–4 days (mostly testing)

### 4.1 Remove Metrics and Analytics Subsystem

| Item | Detail |
|------|--------|
| **Problem** | ~15 API endpoints, 2 frontend pages, 2 backend services (`MetricsService`, `RAGAnalytics`) for developer observability. Zero user value. |
| **Solution** | Delete all metrics/analytics endpoints, services, and frontend pages. Use standard logging for debugging. |

Files to delete:
- [ ] `ai/services/metrics_service.py`
- [ ] `ai/services/rag_analytics.py`
- [ ] `ai/services/logging_config.py` (simplify to basic logging setup)
- [ ] `src/routes/metrics/` (entire directory)
- [ ] `src/routes/analytics/` (entire directory)
- [ ] All `/api/metrics/*` and `/api/analytics/*` endpoints from `main.py`

### 4.2 Evaluate Replacing PyTorch with ONNX Runtime

| Item | Detail |
|------|--------|
| **Problem** | `torch` (2GB+) + `transformers` + `sentence-transformers` make the dependency tree enormous. |
| **Options** | **Option A:** Use `onnxruntime` + pre-converted ONNX embedding model (~50MB). **Option B:** Use an API-based embedding service (Gemini Embedding, OpenAI) — zero local ML deps. **Option C:** Keep as-is if bundle size is acceptable. |

Steps:
- [ ] Benchmark embedding quality: ONNX vs sentence-transformers (should be identical)
- [ ] If ONNX: convert `BAAI/bge-small-en-v1.5` to ONNX, update `EmbeddingService`
- [ ] If API-based: add embedding API call, remove all local ML deps
- [ ] Remove `torch`, `transformers`, `sentence-transformers` from requirements
- [ ] Also evaluate removing the cross-encoder reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) — it loads a second ML model for marginal gain at current scale

### 4.3 Remove Frontend Document Processing Libraries

| Item | Detail |
|------|--------|
| **Problem** | `package.json` includes `mammoth`, `pdfjs-dist`, `xlsx`, `exceljs` for client-side document rendering. Document extraction should be backend-only. |
| **Solution** | If the frontend needs to display documents, serve rendered HTML/text from the backend. Remove client-side processing libs. |

Steps:
- [ ] Audit which frontend components use these libraries
- [ ] For PDF viewing: keep `pdfjs-dist` if used for in-browser PDF display (this is valid)
- [ ] Remove `mammoth`, `xlsx`, `exceljs` — the backend already extracts text from these
- [ ] If `DocumentViewer.svelte` needs them, refactor to fetch rendered content from backend

### 4.4 Simplify the Incremental Update System

| Item | Detail |
|------|--------|
| **Problem** | 5 files (`update_queue.py`, `update_executor.py`, `update_worker.py`, `chunk_differ.py`, `update_strategy.py`) for incremental document updates with priority queues and diff strategies. |
| **Solution** | Replace with a simple "file changed → re-index file" approach. The file monitor detects changes, triggers full re-index of that file. No priority queue, no diff, no strategy. |

Steps:
- [ ] Simplify `FileMonitorService` to call `add_document(force_reindex=True)` on change
- [ ] Remove `update_queue.py`, `update_executor.py`, `update_worker.py`
- [ ] Remove `chunk_differ.py`, `update_strategy.py`
- [ ] Remove `/api/updates/*` endpoints from `main.py`
- [ ] Keep the basic hash-based skip in `add_document()` (if unchanged, don't re-index)

---

## Phase 5 — Feature Alignment: Close the Gap with Claude Cowork

**Why last:** Phases 1–4 give you a clean, lean foundation. Now build the features that
actually differentiate a document workspace.

**Estimated effort:** Ongoing

### 5.1 Code-Aware Chunking

| Item | Detail |
|------|--------|
| **Problem** | All files are chunked as flat text. Code files lose structural context (functions split mid-body, imports separated from usage). |
| **Solution** | Detect file type and use language-aware chunking for code files (by function/class boundaries). Use tree-sitter or simple AST parsing. |

### 5.2 Smarter Context Selection

| Item | Detail |
|------|--------|
| **Problem** | RAG retrieves chunks by similarity, losing document structure. When a user asks about a specific file, you should read the whole file, not scattered chunks. |
| **Solution** | For single-file queries, read the full file content (up to a limit). Reserve chunk-based retrieval for cross-file queries. |

### 5.3 Conversation Memory Improvements

| Item | Detail |
|------|--------|
| **Problem** | Only the last 3 messages are included as conversation history. Long conversations lose context. |
| **Solution** | Implement conversation summarization — periodically summarize older messages into a compact context window. |

### 5.4 File Writing and Editing (Long-Term)

| Item | Detail |
|------|--------|
| **Problem** | Claude Cowork can create and edit files. Klair.ai is read-only. |
| **Solution** | Add endpoints for file creation/modification with confirmation UI. Significant feature — defer until core chat quality is excellent. |

---

## Execution Notes

### Dependency on Phase Order

```
Phase 1 (Foundation) ─── must be first, everything depends on it
    │
    ├── Phase 2 (Token Diet) ─── can start immediately after Phase 1
    │
    ├── Phase 3 (Code Cleanup) ─── can run in parallel with Phase 2
    │
    └── Phase 4 (Dependency Diet) ─── after Phase 3 (needs clean code to refactor deps)
            │
            └── Phase 5 (Features) ─── after Phase 4 (needs lean codebase)
```

### What NOT to Do

- **Do not add new features until Phase 3 is done.** New features on a messy foundation compound the mess.
- **Do not attempt Phase 5 until Phases 1–3 are complete.** Building advanced features on top of PostgreSQL + multi-tenancy + duplicated code will double the work.
- **Do not keep dead code "just in case."** If it's removed in a phase, it's in git history. Delete confidently.

### Metrics for Success

| Metric | Before | Target |
|--------|--------|--------|
| LLM calls per user message | 2–3 | 1 |
| Lines in `main.py` | 1529 | < 80 |
| Lines in `orchestrator.py` | 1487 | < 800 |
| Python dependencies | 25+ (incl. torch) | ~15 |
| Required external services | PostgreSQL + (optional LibreOffice + Tesseract) | None |
| Time to first query after install | Minutes (DB setup) | Seconds |
| Bundle size (Python deps) | ~3GB+ | < 500MB (or < 50MB with API embeddings) |
