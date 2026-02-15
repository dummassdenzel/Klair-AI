# Backend Changes, Improvements & Cloud-Scaling Notes

**Document purpose**: Summary of backend security, performance, and code-quality work completed to date, plus notes on what would need to change when scaling to a cloud-based server.

**Last updated**: February 2026

---

## 1. Summary of Backend Changes and Improvements

### 1.1 Critical Security

| Item | Change |
|------|--------|
| **SQL injection risk** | `search_documents` in `ai/database/service.py` no longer uses f-string patterns with user input. Search uses `func.lower(column).contains(func.lower(literal(query)))` with bound parameters for case-insensitive, safe search. |

### 1.2 High Priority

| Item | Change |
|------|--------|
| **Database connection management** | Replaced `async for session in get_db(): ... break` with `async with AsyncSessionLocal() as session:` everywhere (`database/service.py`, `main.py`, orchestrator, update_executor). Sessions are always closed; write paths use explicit commit/rollback. Reduces risk of connection leaks and pool exhaustion. |

### 1.3 Medium Priority

| Item | Change |
|------|--------|
| **File type validation (preview/file)** | `get_document_preview` and `get_document_file` in `main.py` now validate that the file on disk has the same extension as the DB `file_type` before serving. On mismatch, return 400 so the wrong file is never served. |
| **Timeouts on long-running operations** | **OCR**: `OCRService` uses `ocr_timeout` (config: `OCR_TIMEOUT`); image/scanned-PDF extraction wrapped in `asyncio.wait_for`. **PPTX preview**: `convert_pptx_to_pdf` wrapped with `PPTX_CONVERSION_TIMEOUT`; on timeout return 504. **Directory init**: `initialize_from_directory` in `set_directory` wrapped with `INITIALIZE_DIRECTORY_TIMEOUT` (default 600s); 504 on timeout. |
| **File monitor extension mismatch** | Single source of truth in `file_validator.py`: `BASE_SUPPORTED_EXTENSIONS` and `IMAGE_EXTENSIONS_OCR`. FileMonitor and TextExtractor import these; monitor uses validator’s extensions when available so processor and monitor stay in sync. |

### 1.4 Low Priority / Optimizations

| Item | Change |
|------|--------|
| **Inefficient database queries** | `search_documents` uses one query with a window function `func.count(...).over()` for total count instead of a separate `COUNT(*)` round-trip. Same API and pagination behavior. |
| **Redundant path normalization** | `set_directory` in `main.py` normalizes the path once and reuses it for the “already set” check instead of normalizing twice. |
| **Missing indexes** | `IndexedDocument`: added indexes on `file_type`, `last_modified`, `processing_status`, `indexed_at` (and kept `file_path`). Alembic migration `f1a2b3c4d5e6_add_indexed_document_indexes.py` creates these on existing DBs. |
| **Large file metadata in memory** | `get_stats()` in the orchestrator now requests at most 20 file paths from the DB and returns them as `indexed_files` plus `indexed_files_count`, keeping response size bounded. |
| **Duplicate code (file validation)** | **UpdateExecutor**: Accepts optional `file_validator`; uses shared instance from orchestrator and a single `_get_file_metadata_and_hash()` helper instead of creating `FileValidator()` and calling metadata/hash in three places. **main.py**: Directory picker file count uses `BASE_SUPPORTED_EXTENSIONS` from `file_validator` instead of a hardcoded set. |
| **Response generation speed** | **Retrieval**: Semantic search and BM25 run in parallel in the orchestrator (`asyncio.gather`) so retrieval latency is reduced. **Post-response**: Document linking (get-or-create doc + link to chat) runs in parallel for all sources via `asyncio.gather` instead of a sequential loop. **Future**: Streaming LLM output (SSE or streaming JSON) would improve perceived speed (time to first token); would require a streaming chat endpoint and client updates. |

### 1.5 Still Open (from audit)

- **§11** Input validation on autocomplete (`q` length, `limit` cap) — fix suggested in audit.
- **§12** Error information leakage — generic 500 in production suggested.
- **§20** Connection pooling — explicit `pool_size`, `max_overflow`, `pool_pre_ping`, `pool_recycle` on the SQLAlchemy engine suggested.
- **§21–23** Code quality: consistent error handling, magic numbers in config, type hints.
- **§25–26** Refactoring: extract file-serving logic, configuration management (e.g. Pydantic validation, env-specific configs).

---

## 2. What Would Need to Change for Cloud-Based Scaling

When moving from a single on-prem or dev server to a cloud-based, scalable deployment, the following areas will need attention.

### 2.1 File System and Document Storage

- **Current**: Documents are read from a **local directory** chosen by the user (`set_directory`). Paths are stored in the DB; preview and file serving read from the same local filesystem.
- **Cloud**: Local disk is not shared across instances and may be ephemeral.
  - **Change**: Store documents in **object storage** (e.g. S3, GCS, Azure Blob). Ingest: upload to object storage and store object key (and optionally a local cache path) in the DB. Serve files and previews from object storage (or a CDN) by key, not by local path.
  - **Impact**: `get_document_file`, `get_document_preview`, directory picker, file monitor, and the orchestrator’s “current directory” concept all assume a local root directory; they would need to be refactored to work with object keys and a storage abstraction (e.g. `DocumentStorageService` with `get_stream(key)`, `exists(key)`, list-by-prefix, etc.).

### 2.2 Directory Picker and UI Assumptions

- **Current**: `/select-directory` uses a **GUI directory picker** (e.g. tkinter) that runs on the server and returns a path. This only works when the server has a display and user interaction.
- **Cloud**: Typical cloud backends are headless and multi-tenant; users don’t “pick a folder” on the server.
  - **Change**: Replace with **client-driven upload** or **cloud storage integration**: user selects or uploads files/folders in the browser (or connects a cloud drive); backend receives file list or object keys and indexes from that. Remove or replace the server-side directory picker for production.

### 2.3 Vector Store and BM25 (Chroma / in-process)

- **Current**: **Chroma** (and in-process BM25) run inside the app process, with persistence to a **local `persist_dir`** (often tenant-scoped via `tenant_registry`). State is on local disk.
- **Cloud**: Multiple app instances don’t share local disk; scaling out means each instance would have its own Chroma/BM25 state unless shared.
  - **Change**: Move to **managed or shared vector/search** services, e.g.:
    - Vector: Pinecone, Weaviate, Qdrant, pgvector, or a dedicated Chroma deployment with shared storage.
    - Keyword: Elasticsearch/OpenSearch, or a shared BM25 index.
  - **Impact**: Replace `VectorStoreService` and `BM25Service` implementations (or add backends) that use remote APIs or shared DB (e.g. pgvector) instead of local Chroma + local files. Tenant isolation (per-directory or per-workspace) would be by namespace/collection/tenant ID in the chosen service.

### 2.4 Database and Connection Pooling

- **Current**: Single PostgreSQL URL; engine created without explicit pool settings (see §20 in audit).
- **Cloud**: Multiple instances and higher concurrency require controlled connection usage.
  - **Change**: Add **explicit connection pool** settings (e.g. `pool_size`, `max_overflow`, `pool_pre_ping`, `pool_recycle`) as in the audit. Use a **managed PostgreSQL** service (RDS, Cloud SQL, etc.) and ensure `DATABASE_URL` uses SSL and is not over-subscribed (pool size × instances ≤ DB max connections).

### 2.5 Multi-Tenancy and Global State

- **Current**: Tenant/directory context is handled via `TenantRegistry` and in-memory state (e.g. “current directory”, document processor per tenant). Some global or process-local state may still exist.
- **Cloud**: Multiple instances and/or serverless mean no single process “owns” a user session; state must be explicit and storable.
  - **Change**: Make tenant/session context **explicit on every request** (e.g. tenant ID or workspace ID in headers or auth). Store tenant-to-config mapping (e.g. persist_dir, storage bucket) in DB or config service. Avoid relying on in-memory global state for routing; use **stateless** request handling with tenant ID resolved from auth/session.

### 2.6 Secrets and Configuration

- **Current**: Config from env/`.env` (e.g. `DATABASE_URL`, API keys). No formal distinction between dev and production.
- **Cloud**: Secrets should not live in repo or plain env in production.
  - **Change**: Use a **secrets manager** (e.g. AWS Secrets Manager, HashiCorp Vault, cloud provider secret storage) and inject secrets at runtime. Use **environment-specific config** (e.g. `ENVIRONMENT=production`) for stricter validation, generic error messages (§12), and feature flags.

### 2.7 LibreOffice / OCR and Heavy Dependencies

- **Current**: PPTX preview depends on **LibreOffice** on the server; OCR may use **Tesseract** or similar. Both are process-heavy and assume a fixed environment.
- **Cloud**: Ephemeral or auto-scaled instances may not have these installed; cold starts and CPU/memory limits can affect long-running conversions.
  - **Change**: Consider **dedicated worker processes or queues** for PPTX conversion and OCR (e.g. Celery, cloud queues, or serverless functions). Optionally replace with **managed APIs** (e.g. document conversion / OCR services) so the main app stays lightweight and stateless.

### 2.8 Timeouts and Long-Running Work

- **Current**: Timeouts added for OCR, PPTX conversion, and directory initialization (see §14). Work runs in the API process.
- **Cloud**: API timeouts (e.g. 30–60s) are often shorter than full directory init or large-file OCR.
  - **Change**: For “set directory” / full scan, consider **async jobs**: return 202 with a job ID; background worker does the work; client polls or uses SSE/WebSocket for status. Same for large OCR or conversion jobs. Keep timeouts for any remaining in-request work and align with platform limits (e.g. serverless max duration).

### 2.9 Observability and Health

- **Current**: Logging and some metrics exist; health/readiness may be implicit.
- **Cloud**: Need to support load balancers and orchestrators (Kubernetes, ECS, etc.).
  - **Change**: Add **explicit health/readiness endpoints** (e.g. `/health`, `/ready`) that check DB and, if applicable, vector/store connectivity. Use **structured logging** (e.g. JSON) and ship to a central log/APM service. Optionally expose metrics (e.g. Prometheus) for scaling and alerting.

### 2.10 Summary Table

| Area | Current | For cloud scaling |
|------|--------|--------------------|
| Document storage | Local directory on server | Object storage (S3/GCS/Blob) + key-based access |
| Directory picker | Server-side GUI (tkinter) | Client upload or cloud storage integration |
| Vector / keyword search | Chroma + BM25 on local disk | Managed vector DB + search (or pgvector + shared BM25) |
| DB connections | No explicit pool config | Pool settings + managed PostgreSQL |
| Tenant/state | In-memory / registry | Stateless; tenant ID per request; config in DB/secrets |
| Secrets | Env / .env | Secrets manager |
| PPTX / OCR | In-process, LibreOffice/Tesseract | Worker queue or managed APIs |
| Long-running work | In-request with timeouts | Async jobs (202 + poll/SSE) |
| Observability | Logging | Health/ready, structured logs, metrics |

---

## 3. References

- **Backend audit (full list of issues and resolutions)**: `BACKEND_AUDIT_REPORT.md`
- **Database migrations**: `ai/alembic/versions/`
- **Config and env**: `ai/config.py`, `.env` (and §26 refactor suggestions in audit)
