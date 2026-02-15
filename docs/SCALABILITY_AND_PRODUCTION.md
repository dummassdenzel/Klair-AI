# Scalability and Production Readiness

**Purpose**: Clarify whether the current design is scalable, suitable for production, and appropriate for **general-purpose use** (any document types, any users, globally)—not tied to a specific domain like “delivery notes” or a single folder.

**Last updated**: February 2026

---

## 1. General-Purpose Design

The application is **domain-agnostic**:

- **Query classification** does not hardcode document types. It distinguishes “list **all** documents” (no filter) vs “list/find documents **matching** a type, name, or content” (e.g. “delivery notes”, “invoices”, “contracts”, “Q4 reports”—any category). The same logic works for any corpus and any user wording.
- **RAG pipeline** (semantic + BM25 → rerank → LLM) is generic: it works on whatever documents are indexed (PDFs, spreadsheets, notes, etc.) and whatever the user asks.
- **Streaming, persistence, and API** do not depend on document kind or user identity; they work the same for any tenant and any content.

So **yes**: the **approach** is suitable for general-purpose use globally. Nothing in the design restricts it to “delivery notes” or a single use case.

---

## 2. Is the Current Implementation Scalable?

**Short answer**: It scales **within a single process and single machine** (one directory/tenant per context, moderate document count). It is **not** yet built for **horizontal scaling** or **global multi-tenant SaaS** at large scale.

| Aspect | Current state | Scalable? |
|--------|----------------|-----------|
| **Logic (RAG, classification, streaming)** | Generic; no domain lock-in | ✅ Yes — design is sound |
| **Single tenant / one directory** | In-memory tenant registry; one “current directory” per tenant | ✅ Fine for single-tenant or few tenants on one server |
| **Document storage** | Local filesystem path (server-side directory) | ❌ Does not scale across multiple servers or regions |
| **Vector + keyword search** | Chroma + BM25 on local disk (tenant-scoped persist_dir) | ❌ Single-node only; no shared index across instances |
| **Database** | PostgreSQL (or SQLite in dev); no explicit pool tuning | ⚠️ Postgres scales with pool/config; SQLite is single-writer |
| **Indexing / OCR / PPTX** | In-process; same API process does everything | ❌ Long-running work blocks or times out; no job queue |
| **Secrets / config** | Env / .env | ⚠️ OK for small deployments; not ideal for large production |
| **Auth / multi-tenant** | Tenant ID (e.g. from header); no full auth model | ⚠️ Needs proper auth and tenant isolation for “global” SaaS |

So: **current implementation = good for single-tenant or small multi-tenant on one machine**. For “scale out” (many tenants, many instances, global), you need the changes described in **§3** and in `BACKEND_CHANGES_AND_CLOUD_SCALING.md`.

---

## 3. Is This the Best Production Approach?

**For production**, the **patterns** you have are the right ones:

- **RAG over your own index** (semantic + keyword + optional rerank) is the standard, production-ready way to build “ask over my documents” for any domain.
- **Streaming responses** improve perceived performance and are common in production chat APIs.
- **Query classification** (list-all vs search/filter) keeps behavior correct without hardcoding domains; for higher scale you might add caching or a cheaper model for classification.
- **Stateless API** with tenant/directory context per request is the right direction; making it fully stateless (tenant from auth, no in-memory global state) is the next step for multi-instance production.

**Best production approach** for **global, scalable** use typically implies:

1. **Document storage**: Object storage (S3/GCS/Blob) by tenant; no server-side “pick a folder” on the server.
2. **Vector + search**: Managed or shared (e.g. Pinecone, Weaviate, pgvector, OpenSearch) with tenant isolation (namespace/collection per tenant or workspace).
3. **Database**: PostgreSQL with connection pooling and, if needed, read replicas; no SQLite in production for multi-tenant.
4. **Indexing / heavy work**: Async job queue (e.g. Celery, Cloud Tasks) so the API stays responsive and you can scale workers independently.
5. **Auth & tenancy**: Proper auth (e.g. OAuth2, API keys) and tenant ID on every request; tenant config and limits in DB or config service.
6. **Secrets**: Secrets manager (e.g. AWS Secrets Manager, Vault); no secrets in repo or plain env in production.
7. **Observability**: Health/readiness endpoints, structured logging, metrics (e.g. Prometheus), and optional APM.

The existing doc **`BACKEND_CHANGES_AND_CLOUD_SCALING.md`** already outlines these in detail (object storage, vector DB, pool, tenant/state, secrets, workers, health). So: **the way you’re building the app is production-style; the “best production approach” for global scale is to evolve the **implementation** along that doc, not to change the high-level RAG/streaming/classification design.**

---

## 4. Recommendation Summary

| Goal | Recommendation |
|------|----------------|
| **General-purpose use (any docs, any users, globally)** | ✅ The design supports it; no change needed to stay domain-agnostic. |
| **Production today (single tenant or few, one server)** | ✅ Current implementation is acceptable; add connection pooling (§20 in audit), tighten error handling and config, and use Postgres in production. |
| **Production at scale (many tenants, many instances, global)** | Follow **`BACKEND_CHANGES_AND_CLOUD_SCALING.md`**: object storage, shared vector/search, DB pooling, job queue for indexing/OCR, auth and tenant isolation, secrets manager, health and metrics. |

So: **yes, the approach is scalable and production-appropriate in principle**, and it is **general-purpose**. The current code is a solid base for single-tenant or small multi-tenant; for large-scale global production, the same architecture should be kept and the implementation evolved as in the cloud-scaling doc.
