# SaaS & Deployment Direction

**Purpose:** Technical and product direction for Klair AI as a **production** app used **globally** for **generic document use cases**. This doc reflects advisor-level recommendations and re-evaluates where documents should live and what “best” means for this product.

**Last updated:** February 2026

---

## 1. What “production, global users, generic use” implies

- **Multi-user / multi-tenant:** Many users or organizations; each sees only their own documents and chats.
- **Generic use:** Any document types (schoolwork, office, permits, invoices, contracts, etc.) — the app is already domain-agnostic.
- **Auth required:** Every user is identified and authorized; no anonymous access to document/chat APIs.

“Production” and “global” do **not** by themselves require documents to live in your cloud. They require a clear architecture, auth, and a deployable product — which can be **local-first** (documents on the user’s device) or **cloud-first** (documents in your cloud). The choice is product and trade-off driven.

---

## 2. Why would documents be in the cloud? (And why they don’t have to be)

### Reasons people put documents in the cloud

- **Access from anywhere:** User logs in from another device and sees the same docs (browser, phone, work laptop). The backend has the data, so no “my files are on my other PC.”
- **Single backend:** One deployment does indexing and RAG for everyone; you don’t ship or support a backend that runs on each user’s machine.
- **Simpler install for the user:** “Use in browser” — no desktop install, no “point to a folder” on a server. Good for non-technical users who don’t want to run anything.

### Why documents do *not* have to be in the cloud

- **Privacy and trust:** Many users (and enterprises) do not want to upload sensitive documents to a third party. Local = data never leaves their control (except optional LLM calls).
- **Cost and scale:** Storing and indexing every user’s documents in your cloud is expensive (storage, vector DB, compute). You pay per GB and per user; abuse (e.g. terabytes per user) is your problem.
- **Liability and compliance:** You become the data custodian. Breaches, GDPR, HIPAA, and retention are on you. Local keeps custody with the user.
- **Your app already works with local documents.** The current design is “user points at a directory; backend (local or user-run) indexes and runs RAG.” That’s a valid, production-ready product: a **desktop or locally-run app** that doesn’t require upload.

So: **documents in the cloud are a product choice** (we want “access from anywhere” and “one backend”) **with real trade-offs** (privacy, cost, custody). They are **not** a technical requirement for “production” or “global users.”

---

## 3. Two models — and what’s best for this application

| Model | Documents live in | Where RAG runs | Your cloud holds |
|-------|--------------------|----------------|-------------------|
| **A. Local-first (primary)** | User’s device (or their server/NAS). | User’s machine (or their server). Backend can be bundled with desktop app or run by user. | **Only:** auth, identity, license/subscription, app updates, optional anonymized telemetry. **Not** document content or embeddings. |
| **B. Cloud documents** | Your object storage (upload or linked drive). | Your backend. | Document files, embeddings, metadata, chat. Full custody. |

**Recommendation for *this* application (production, global, generic, privacy-aware):**

- **Make local-first the primary model.**  
  Documents stay on the user’s device. The app is a **desktop app** (or “desktop + local backend”): user installs it, points at a folder (or the app has access to local/network paths), and indexing + RAG run on their side. Your **cloud** is used for: **auth** (who is using the app), **license / subscription** (e.g. “pro” features, seat count), and **updates**. No document upload required. That’s how many successful “document” and “search” products work (e.g. local dev tools, desktop search, note-taking with local storage).

- **Offer cloud documents as an optional add-on** for users who explicitly want “access from anywhere” and accept uploading or linking a drive. Then you take on custody and cost for those users only; the default path stays private and local.

So: **don’t assume documents must be uploaded to the cloud.** Default to **documents on the user’s device**; add cloud as an **optional** workspace for those who want it. That’s the best fit for a production, global, generic, privacy-conscious document RAG app unless you deliberately want to be a “we host your docs” product (with the attendant cost and liability).

---

## 4. PWA vs desktop app — recommendation

- **If your primary is local-first (documents on device):**  
  The app needs **access to the user’s files** (local or network). Browsers can do that in limited ways (File System Access API, or drag-and-drop upload). For **full** local folder access, watch for changes, and run a backend that indexes and serves RAG, a **desktop app** (e.g. **Tauri** or **Electron**) is the better fit: it bundles or runs the backend locally and talks to your cloud only for auth/license/updates. So for **local-first**, **desktop app (Tauri preferred for size and security)** is the primary client; PWA is an option only if you restrict to “upload for this session” or “connect drive” and don’t need true “index my whole PC.”

- **If your primary is cloud documents:**  
  **PWA** works well: user logs in, uploads or connects a drive, and uses the app in the browser; no desktop install. You can add a desktop wrapper later for app-store or offline shell.

**Summary for this app (local-first primary):**  
- **Primary client:** **Desktop app** (e.g. Tauri) that runs (or bundles) your backend locally, indexes user’s folders, and uses your cloud only for auth + subscription + updates.  
- **Optional:** PWA or web app for the **optional cloud workspace** (upload/drive) when you add it.

---

## 5. High-level architecture (local-first primary, optional cloud)

**Local-first path (primary)**

- **Client:** Desktop app (e.g. Tauri) that either embeds your existing Svelte UI or loads it from your CDN. The app has access to the user’s files (folder picker, or configured paths).
- **Backend:** Your **current FastAPI + orchestrator** runs **on the user’s machine** (bundled with the desktop app or started by it). It reads from the user’s chosen directory, indexes into local Chroma + BM25, and runs RAG. LLM calls go to Gemini (or Ollama if the user runs it locally for full privacy).
- **Your cloud:** A **small** service: **auth** (login, OAuth or email), **license/subscription** (e.g. check entitlement), and **app updates** (e.g. version check, download installer). Optionally store **preferences** or **sync metadata** (e.g. which folders they added) if the user opts in. **No document content or embeddings** in your cloud.

So: your current codebase (directory, Chroma, BM25, orchestrator, LLM) stays as the **local backend**; you add a thin **cloud service** for identity and licensing only.

**Optional cloud-workspace path (add-on)**

- When you add “cloud workspace”: user uploads or connects a drive; your **cloud** backend then has document storage, indexing, and RAG (as described earlier in this doc). That’s a second deployment path for users who choose it.

---

## 6. What to do with the current codebase (local-first primary)

- **Keep as-is for the local path:** RAG pipeline, classification, streaming, retrieval, rerank, LLM integration, directory picker, Chroma, BM25. They already form a working local document RAG app.
- **Add for production (any path):**  
  1. **Authentication** (Tier 0) — used by your **cloud** service (login, subscription check). The local backend can validate a token or session issued by your cloud before serving RAG.  
  2. **Health, config validation, input validation** (Tier 1).  
  3. **Connection pooling, generic 500 in production** (Tier 2) for any cloud DB you add.
- **Add only when you offer cloud workspace:** Upload API, object storage, tenant-scoped indexing in the cloud, and a separate cloud backend path. Not required for the primary (local-first) product.

---

## 7. Suggested order (as your technical adviser)

1. **Ship the current app as a desktop app** (e.g. Tauri) or “local backend + web UI” so users can run it on their machine and point at a folder. No document upload; this is your **primary** product.  
2. **Add a minimal cloud service** for **auth** and **license/subscription** only. Desktop app calls it to log in and to check entitlement; no document data in the cloud.  
3. **Health + config validation** (Tier 1) for both local backend and cloud service.  
4. **Optionally later:** Add “cloud workspace” (upload/drive + cloud indexing) for users who want access-from-anywhere and accept uploading.  
5. **Then:** Connection pooling, generic 500, Pydantic config, etc., per NEXT_IMPLEMENTATIONS.md.

That gives you a **production app**: desktop (or local) first, privacy-preserving by default, with a small cloud footprint and an optional cloud path when you want it.

---

## 8. Privacy implications and privacy-focused approach

### How cloud SaaS affects privacy

When documents and indexing move to **your cloud**:

- **Documents and derived data** (text, embeddings, chat) are stored on your (or your provider’s) infrastructure. Your backend — and, depending on design, your cloud provider and LLM provider — can technically access or process that data.
- **Risks to user privacy** include: unauthorized access (insider or breach), use of content for training or analytics unless explicitly forbidden, retention beyond what users expect, and jurisdiction (e.g. data in a different country than the user).
- **LLM provider:** Today you use e.g. Gemini; prompts (query + retrieved chunks) are sent to the provider. Their policies (e.g. no training on API data) apply, but the content still leaves your control for the duration of the request.

So: **cloud SaaS improves reach and UX but increases the privacy surface.** The “best privacy-focused approach” is to minimize what you store, who can access it, and how long you keep it — and to offer a **local-only** path for users who want maximum control.

---

### Privacy options (from strongest to weakest)

| Approach | Privacy level | Complexity | SaaS fit |
|----------|----------------|------------|----------|
| **Local-only** | Highest: data never leaves the device. | Medium: desktop/local backend or full local stack. | Poor: not a central SaaS; per-user install. |
| **E2E encrypted cloud** | High: you store only ciphertext; user holds keys. | High: semantic search over encrypted content is hard (encrypted search / FHE or metadata-only search). | Possible but RAG is limited or complex. |
| **Encrypted at rest + strict policies** | Medium–high: data encrypted on disk; you hold keys; strict access, retention, no training. | Low–medium: standard cloud crypto + ops. | Good: works with full RAG and SaaS. |
| **Cloud with transparency and controls** | Medium: data on your servers; clear policy, delete-all, short retention, no training. | Low. | Good. |
| **Cloud with no clear policy** | Lowest. | — | Not recommended. |

**Practical takeaway:**  
- **Best privacy-focused approach that still works as SaaS:** **Encrypted at rest + strict policies + optional local mode** (see below).  
- **Maximum privacy (no cloud docs):** **Local-only mode** — documents and indexing stay on the user’s machine; your “SaaS” is then auth + optional sync or optional cloud features, or a separate “local app” product.

---

### Recommended privacy-focused approach (for your SaaS)

Aim for a **layered** model that works with cloud documents and RAG while being as privacy-focused as practical:

1. **Encryption and access**
   - **Encrypt at rest:** All document blobs, DB, and vector/index data encrypted at rest (e.g. S3/disk encryption, PostgreSQL TDE or encrypted volumes). Use a reputable cloud provider and avoid holding keys in app code.
   - **Encrypt in transit:** HTTPS only; TLS for DB and internal services.
   - **Access control:** Auth on every request; tenant isolation so one user never sees another’s data. Audit logging for sensitive access (e.g. admin, bulk export).

2. **Minimize and retain**
   - **Minimal retention:** Define retention (e.g. “delete document content 90 days after user deletes” or “delete all data 30 days after account deletion”). Implement scheduled jobs and a “delete my data” flow.
   - **No training on user data:** In your terms and privacy policy, state that user documents and chats are **not** used to train your (or third-party) models. Use LLM providers that contractually do not train on API data (e.g. Gemini as configured) and document that.

3. **Transparency and control**
   - **Privacy policy and docs:** Clearly state what you store, where it lives, how long you keep it, who (you, provider, LLM) can see it, and that you don’t train on it.
   - **User controls:** “Delete all my documents,” “Delete my account and all data,” “Export my data.” Implement these and surface them in the UI.

4. **Optional local-only mode (best for privacy-minded users)**
   - Offer a **local mode** (desktop or “run backend on your machine”): documents stay on the user’s PC; indexing and RAG run locally; nothing is sent to your cloud except optional auth/telemetry if the user agrees. This is the **most privacy-focused** option and reuses your current “directory on server” design when the “server” is the user’s own machine.
   - In the UI: “Use in browser (cloud)” vs “Use locally (nothing leaves your device).” Local mode can still check for updates or optional anonymous usage stats if you want, with explicit consent.

5. **Region and compliance**
   - If you have EU (or other regulated) users: consider **region-specific deployment** or storage (e.g. EU bucket/DB) and document it. Plan for **GDPR** (right to access, erase, portability, lawful basis).

**Summary:**  
- **Default (cloud SaaS):** Encrypt at rest and in transit, strict tenant isolation, short retention, no training on user data, clear policy and delete/export controls.  
- **Optional:** Local-only mode for users who want maximum privacy (data never leaves device).  
- **Best privacy-focused approach overall:** Combine **strong cloud hygiene** (encryption, retention, no training, transparency) with an **optional local-only path** so users can choose the trade-off (convenience vs. maximum privacy).

---

## 9. Local-only mode: disadvantages, why optional, trade-offs, and providers

### Disadvantages of local-only mode

- **No “one app, anywhere”:** User must install and run the app (or backend) on each device. No “log in on a friend’s laptop and see my docs” — there are no “your docs” in the cloud.
- **Install and ops burden:** User (or IT) installs, configures, and updates the app. You have to ship installers, handle OS differences, and support “it doesn’t run on my machine.”
- **No central service revenue:** Hard to charge a recurring “SaaS” fee for a one-time install; monetization is usually license or support, not subscription per seat.
- **LLM still leaves the device:** For RAG you still call an LLM (e.g. Gemini/Ollama). With Gemini, **query + retrieved chunks** leave the machine. Only **Ollama** (or similar local models) keeps everything on-device; that means lower quality or heavier local hardware.
- **Backup and durability:** If the user’s disk dies and they didn’t back up, their index and metadata are gone unless you add your own sync/backup (which can blur into “cloud” again).
- **Scaling and support:** You don’t control the environment (OS, RAM, disk). Harder to debug and to guarantee “it works for everyone” across many devices.

So local-only is **best for privacy and control**, but **worse for reach, convenience, and running a single global SaaS product**.

---

### Why make local-only “optional” instead of the only mode?

- **Your goal is production SaaS for global users.** That implies a **central service** (your backend in the cloud) that many users hit from browsers or thin clients. If the **only** mode is local-only, there is no central service — it’s a **desktop/local app product**, not SaaS. So for “SaaS desktop app, global users,” the **primary** offering has to be cloud-backed; local-only is an **option** for users who want maximum privacy.
- **Optional** means: **default path = cloud** (sign up, upload or connect drive, use in browser/PWA). **Secondary path = local mode** (“Use locally” or “Desktop app – local only”) for privacy-focused users. You’re not forcing everyone to the cloud; you’re not forcing everyone to install. Each user chooses the trade-off.

You *could* make local-only the **only** product (no cloud at all). Then you’re not SaaS; you’re a local/desktop app. That’s a valid product, but it’s a different one from “SaaS for global users.”

---

### Trade-offs at a glance

| Dimension | Cloud (default) | Local-only (optional) |
|-----------|------------------|------------------------|
| **Privacy** | Data on your servers; you can minimize with encryption, retention, no training. | Data never leaves device (except LLM if not local). |
| **Reach** | Any device, browser, “log in anywhere.” | Per-device install; no “my docs in the cloud.” |
| **Convenience** | No install; updates when you deploy. | User installs and updates; possible breakage. |
| **LLM** | Use best cloud models (e.g. Gemini). | Use local (e.g. Ollama) for full privacy, or accept cloud LLM. |
| **Revenue** | Recurring SaaS subscription. | License/support; harder to do subscription. |
| **Support** | You control backend and env. | Many envs; harder to reproduce issues. |
| **Backup / durability** | You manage durability and backups. | User’s responsibility unless you add sync. |

---

### What you actually need in the cloud (and which providers fit)

**If your primary is local-first (recommended):**

- You need **only**: **auth** (who is the user, login/signup) and **license/subscription** (e.g. free vs paid, seat count). Optionally a small **metadata store** (user profile, which folders they added for sync — no document content).
- **You do not need:** document storage, vector DB, or indexing in the cloud for the primary product. So don’t choose a provider because it has Storage or pgvector; choose because it does **auth + optional tiny DB** well and is simple to operate.

**Provider options (no single “best” — pick by trade-offs):**

- **Auth-only, minimal backend:**  
  **Clerk**, **Auth0**, or **Firebase Auth** give you login (email, OAuth) and issue JWTs or session tokens. You can store subscription tier in their user metadata or in a **tiny** DB (e.g. Supabase Postgres with one `users` table, or Neon, or even SQLite on a small VPS). Best when you want to move fast and keep the cloud surface minimal. Supabase is not required here; Clerk + a small Postgres (or no DB at all if you encode tier in JWT) is enough.

- **Auth + one database for users/licenses:**  
  **Supabase** (Auth + Postgres) or **Firebase** (Auth + Firestore) give you auth and a place to store user id, email, subscription status, etc. Supabase is a good fit **if** you like having Auth and Postgres in one place and might add cloud workspace later (then you already have Postgres and can add Storage + pgvector). Don’t adopt Supabase only because you know it — adopt it if you want a single BaaS for auth + relational data and possibly future document storage.

- **Full control:**  
  Small **FastAPI** (or similar) service with **Postgres** (e.g. Neon, Railway, or your own) and **auth** via JWT (you implement login with bcrypt + refresh tokens, or plug in OAuth). No third-party BaaS. Best when you want no vendor lock-in and are fine maintaining auth and a small schema.

**If you add cloud workspace later (documents in the cloud):**

- Then you need: **auth**, **database** (users, tenants, document metadata, chat), **file storage** (document blobs), **vector search** (embeddings).  
- **Supabase** is then a **good fit**: Auth + Postgres (with pgvector for vectors) + Storage in one product. Alternatives: **Auth0/Clerk** + **Neon/Railway Postgres** + **S3/R2** + **pgvector or Pinecone**. Choose by team familiarity, cost, and scale.

**Bottom line:** For **this application** with **local-first primary**, the best production approach is: **don’t upload documents to the cloud by default.** Use the cloud for **auth and subscription only**. Pick a provider that’s good at that (Clerk, Auth0, Supabase Auth, or a minimal custom backend). Supabase is a reasonable choice if you want one place for auth + DB and might add cloud workspace; it’s not uniquely “best” — choose based on your preference for simplicity vs control and on whether you’ll add cloud documents later.
