# Next Implementations — Actionable Roadmap

**Purpose:** Concrete next steps you can implement, in priority order. Each item is scoped so it can be done in one focused change.

---

## When is authentication more important?

- **Auth is more important** if: the app will be used by **multiple users**, exposed on a **network** (not just localhost), or holds **sensitive documents**. Without auth, anyone who can reach the API can use it and see the same data. Implement auth **before or alongside** Tier 1 so that tenant/session identity is in place and you don’t have to retrofit it later.
- **Hygiene (Tier 1) is more important first** if: the app is **single-user**, only on **localhost**, or behind a **reverse proxy / VPN** that already restricts access. In that case health, config validation, and input validation are quick wins; add auth when you open the app to more users or the internet.

**Recommendation:** If you plan to have multiple users or deploy beyond your machine, treat **authentication** as Tier 0 and do it next. If it’s single-user / local for now, you can do Tier 1 first and add auth when you need it.

---

## Tier 0 — Foundation (do first if multi-user or exposed)

### 0. Authentication

- **What:** Identify who is using the app and protect API routes so only authenticated (and optionally authorized) users can call them.
- **Why:** Without auth, anyone with network access can use the API and see documents/chats. Auth is the base for per-user data, quotas, and audit.
- **Implementation options (pick one and grow):**
  - **Simple API keys:** One shared secret in a header (e.g. `X-API-Key`). Good for single-tenant or internal tools; validate in a FastAPI dependency and return 401 if missing/invalid.
  - **Session-based auth:** Login (e.g. username/password or magic link), set a signed cookie or session ID; validate session on each request. Needs a user store (DB table) and password hashing (e.g. bcrypt).
  - **JWT:** Stateless tokens (e.g. after login or OAuth). Validate signature and expiry on each request; put user/tenant ID in the token so you don’t need a DB hit every time.
  - **OAuth2 / OIDC:** “Login with Google/GitHub” — delegate identity to a provider; get tokens and map to your own user/tenant. Best for “sign in with…” and multi-tenant SaaS.
- **Where:** New auth module (e.g. `ai/auth.py` or `ai/services/auth.py`) for token/session validation; FastAPI `Depends()` to protect routes; optional login/signup endpoints. Wire tenant/user ID from auth into your existing tenant context (e.g. replace or derive `X-Tenant-ID` from the authenticated user).
- **Scope:** Start with “all document/chat endpoints require a valid auth” (401 if not authenticated). Add roles (e.g. admin vs user) later if needed.

---

## Tier 1 — Quick wins (production hygiene)

### 1. Health / readiness endpoint

- **What:** Add `GET /api/health` (and optionally `GET /api/ready`) that return 200 when the app and its dependencies are usable.
- **Why:** Load balancers, Docker/Kubernetes, and monitoring need a single endpoint to check liveness/readiness.
- **Implementation:**
  - **Liveness:** Return 200 with `{"status": "ok"}` (app process is up).
  - **Readiness:** Optionally check DB (e.g. `SELECT 1`) and return 503 if DB is unreachable; otherwise 200. Optionally check Chroma/vector store if you want “index available” as part of ready.
- **Where:** `ai/main.py` — add one or two routes, minimal logic.

### 2. Startup config validation

- **What:** On app startup, validate required settings and fail fast with a clear error message.
- **Why:** Avoid cryptic runtime errors when `GEMINI_API_KEY` or `DATABASE_URL` is missing or invalid.
- **Implementation:**
  - If `LLM_PROVIDER=gemini`: require `GEMINI_API_KEY` (non-empty).
  - Require `DATABASE_URL` to be set and parseable (e.g. starts with `postgresql://` or `sqlite`).
  - Log a warning or error and exit (or raise) before accepting requests if validation fails.
- **Where:** `ai/main.py` in lifespan/startup, or a small `validate_config()` called from there; use `ai/config.py` settings.

### 3. Input validation on search/autocomplete (§11)

- **What:** Validate `q` (query) length and `limit` cap on document search/autocomplete endpoints.
- **Why:** Prevents abuse and avoids unnecessarily large queries.
- **Implementation:** Cap `q` length (e.g. 500 chars) and `limit` (e.g. max 100); return 400 with a clear message when exceeded.
- **Where:** `ai/main.py` — wherever search/autocomplete parameters are read (e.g. `GET /api/documents/search`).

---

## Tier 2 — Audit items (stability and ops)

### 4. Connection pooling (§20)

- **What:** Configure the SQLAlchemy engine with explicit pool settings.
- **Why:** Prevents connection exhaustion under load and improves reliability.
- **Implementation:** Set `pool_size`, `max_overflow`, `pool_pre_ping`, and `pool_recycle` on the async engine (see audit suggestion). Typical values: `pool_size=10`, `max_overflow=5`, `pool_pre_ping=True`, `pool_recycle=3600`.
- **Where:** Where the engine is created (e.g. `ai/database/` or wherever `create_async_engine` is called).

### 5. Generic 500 in production (§12)

- **What:** In production, return a generic error message for unhandled exceptions (e.g. “An error occurred”) and log the real error server-side only.
- **Implementation:** Use an env var (e.g. `ENVIRONMENT=production`). In the global exception handler or FastAPI exception handler, if production: return 500 with a generic message; else return/details as today. Always log the full exception server-side.
- **Where:** `ai/main.py` — add or adjust exception handler and read `ENVIRONMENT` from config.

### 6. Autocomplete/search validation details (§11)

- **What:** If there is a separate autocomplete endpoint, apply the same `q` length and `limit` caps and document them.
- **Where:** Same as (3); ensure all public search/query params are validated.

---

## Tier 3 — Code quality and maintainability

### 7. Pydantic config (optional, §26)

- **What:** Replace the current `Settings` class with a Pydantic `BaseSettings` model so env types and defaults are validated in one place.
- **Why:** Fewer typos, better validation, and a single source of truth for env vars.
- **Where:** `ai/config.py` — migrate to `pydantic_settings.BaseSettings` with `env_file=".env"` and field validators.

### 8. Extract file-serving logic (§25)

- **What:** Move the logic that serves document files/previews (path validation, content-type, streaming) into a small service or helper module instead of inline in route handlers.
- **Why:** Easier to test and reuse; clearer separation of concerns.
- **Where:** New module (e.g. `ai/services/file_serving.py`) and `ai/main.py` routes call into it.

---

## Tier 4 — Later (when scaling or deploying to cloud)

- **Object storage:** Replace local directory with object storage and a `DocumentStorageService` (see `BACKEND_CHANGES_AND_CLOUD_SCALING.md`).
- **Managed vector DB:** Move from local Chroma to pgvector, Pinecone, Weaviate, etc., when you need multi-instance or shared index.
- **Secrets manager:** Use a secrets manager in production instead of plain env for API keys and DB URL.
- **Async jobs:** Move long-running indexing/OCR to a job queue (e.g. Celery, Cloud Tasks) and expose job status via API.

---

## Suggested order to act

- **If you will have multiple users or expose the app beyond localhost:** do **Authentication (Tier 0)** first, then Tier 1 (health, config validation, search validation).
- **If the app stays single-user / local for now:** do Tier 1 first, then add auth when you open it up.

Then:

1. **Health endpoint** — small, high value for any deployment.
2. **Startup config validation** — prevents misconfig in dev and prod.
3. **Search/autocomplete validation (§11)** — quick security/hygiene.
4. **Connection pooling (§20)** — important before higher load.
5. **Generic 500 in production (§12)** — then remaining items as needed.

You can implement (1)–(3) in one session; (4) and (5) in the next. The rest can follow when you focus on refactors or cloud scaling.
