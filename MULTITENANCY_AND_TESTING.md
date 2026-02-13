py# Multi-tenancy: Production Meaning & Testing

## What this means in production (Tauri desktop app, users globally)

### Two deployment models

1. **Backend runs on each user’s machine (typical Tauri desktop)**  
   - Each user runs the app locally; the FastAPI backend is either embedded or started on localhost.  
   - There is effectively **one user per process**.  
   - **You don’t need to send any tenant header.**  
   - All requests use the **default tenant** (`"default"`): one directory, one index (Chroma), one file monitor per app instance.  
   - The change removes **global shared state** (no more “User B overwrites User A” inside the same process). So for a single-user desktop app, behavior stays the same; the code is just correct and ready for multi-tenant if you need it later.

2. **Backend runs on a central server (optional future)**  
   - Many desktop clients connect to one backend (e.g. your cloud).  
   - **Tenant ID** (e.g. `X-Tenant-ID: <user_id>` or workspace id) isolates each user/workspace: separate directory, index, and file monitor.  
   - Bounded registry (e.g. 10 tenants) + LRU eviction avoids unbounded memory when many users are active.

So: **for “users globally on native desktops” with a backend-per-machine, you run in production exactly as today (no headers); for a future shared server, you’d send a tenant id per user/workspace and get isolation and bounded load.**

---

## Your import test result

Your run:

```text
Imports OK
Registry len 0
get_tenant_persist_dir(default)= /data
get_tenant_persist_dir(tenant2)= /data/t_0419236116e3
Done
```

means:

- **Imports OK** – `tenant_registry` and its exports load correctly.  
- **Registry len 0** – New registry has no tenants (expected).  
- **get_tenant_persist_dir(default)= /data** – Default tenant keeps the same path (backward compatible).  
- **get_tenant_persist_dir(tenant2)= /data/t_0419236116e3** – Other tenants get an isolated subdir.  

So the tenant registry and persist-dir logic are working as intended.

---

## How to test that everything works

### 1. Single-tenant (desktop default) – no header

- Start the app (e.g. `uvicorn main:app` from `ai/`).
- In browser/Postman: **do not** set `X-Tenant-ID`.
- Call `POST /api/set-directory` with `{"path": "C:\\SomeFolder"}` (or your test path).
- Call `GET /api/status`: you should see `directory_set: true`, `current_directory`, `processor_ready`, etc.
- Call `POST /api/chat` with a message: should answer using that directory’s index.
- Call `GET /api/documents/autocomplete?q=...`: should use the same index.

If all of that works, your **production-like path** (one user, no tenant header) is good.

### 2. Multi-tenant (optional) – with header

- Same server; use two different tenant ids.
- **User A:** set header `X-Tenant-ID: alice`, `POST /api/set-directory` with path A.
- **User B:** set header `X-Tenant-ID: bob`, `POST /api/set-directory` with path B.
- With `X-Tenant-ID: alice`, call `GET /api/status` → should show path A.
- With `X-Tenant-ID: bob`, call `GET /api/status` → should show path B.
- Chat/autocomplete with each header should use the correct directory/index.

This verifies isolation when you later use a shared server.

### 3. Automated test (tenant registry)

Run the tenant registry tests:

```bash
cd ai
python -m pytest tests/test_tenant_registry.py -v
```

These cover registry get/set/eviction and `get_tenant_persist_dir` so you can confirm behavior after changes.

---

## Summary

| Scenario | Tenant header | Meaning |
|----------|----------------|--------|
| **Desktop app (one user per machine)** | Omit (default) | One directory/index per app; production behavior unchanged. |
| **Shared server (many users)** | `X-Tenant-ID: <user_or_workspace_id>` | Isolated directory + index per tenant; bounded by registry size. |

Your import test already confirms the registry and per-tenant paths work; use the manual steps above to confirm the full app, and the new test file to regression-test the registry.
