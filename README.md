# Klair AI

A document RAG (retrieval-augmented generation) assistant. Point it at a folder; it indexes your files and answers questions about them in chat. Supports web and desktop (Tauri) frontends.

---

## What it does

- **Index documents** from a chosen directory (PDF, Word, Excel, text, etc.). Metadata-first indexing with background content processing; Chroma (vectors) + BM25 (keywords) for retrieval.
- **Chat over your files** with streaming responses. Queries are classified (greeting, general, “list all”, or search) and routed to listing or RAG. Sources are shown per message.
- **Document categories** (optional). At index time, each document is classified into a semantic type (e.g. invoice, permit, receipt, report). For questions like “what are our delivery receipts?” or “total value of them?”, retrieval is filtered by that category so the same set of documents is used consistently and only relevant sources are shown.
- **Follow-up context.** Conversation history is used so follow-ups like “What is the total value of them?” resolve “them” to the same document type as the previous turn.

---

## Stack

| Layer   | Tech |
|--------|------|
| Frontend | SvelteKit, Vite, Tailwind; optional Tauri for desktop |
| Backend  | FastAPI (Python), async |
| RAG      | ChromaDB (vectors), BM25 (keyword), hybrid search + optional reranker |
| LLM      | Ollama (local), Groq, or Gemini — switch via `LLM_PROVIDER` |
| Embeddings | sentence-transformers (e.g. BAAI/bge-small-en-v1.5) |
| DB       | PostgreSQL (sessions, messages, indexed document metadata) |

---

## Setup

### Backend

```bash
cd ai
.venv/Scripts/activate   # or: source .venv/bin/activate
pip install -r requirements.txt
# Set .env (see ai/.env.example or docs). At minimum: DATABASE_URL, LLM_PROVIDER, optional GROQ_API_KEY / GEMINI_API_KEY
alembic upgrade head    # run migrations (includes document_category if applied)
uvicorn main:app --reload
```

### Frontend

```bash
npm install
npm run dev        # web
# or
npm run dev:tauri  # desktop
```

### Environment (backend `ai/.env`)

- **Database:** `DATABASE_URL` (PostgreSQL).
- **LLM:** `LLM_PROVIDER` = `ollama` | `groq` | `gemini`; then the matching key and model (e.g. `GROQ_API_KEY`, `GROQ_MODEL`).
- **Chroma:** `CHROMA_PERSIST_DIR` (or `CHROMA_PERSIST_DIRECTORY`); default `./chroma_db`.
- **Embeddings:** `EMBED_MODEL_NAME` (default BAAI/bge-small-en-v1.5).
- **Groq limits (optional):** `GROQ_MAX_CONTEXT_CHARS`, `GROQ_MAX_SIMPLE_PROMPT_CHARS`, `GROQ_MAX_LISTING_CONTEXT_CHARS` if you hit 413 on a lower-TPM model.

See [docs/LLM_PROVIDERS_AND_GROQ.md](docs/LLM_PROVIDERS_AND_GROQ.md) and [docs/LLM_PROVIDER_ADAPTERS.md](docs/LLM_PROVIDER_ADAPTERS.md) for provider details.

---

## Main features (current)

- **Query classification & routing**  
  Greetings and “list all” / “what kind of files” go to document listing (full list from DB); other questions go to RAG (hybrid retrieval). Classification can use conversation history.

- **Hybrid retrieval**  
  Semantic (Chroma) + BM25, with optional reranking. For “list all X” / “total value of X” (aggregation), when document categories exist we fetch **all** chunks for that category so the document set is deterministic (same 20 docs for “what are our delivery receipts?” and “total value of them?”).

- **Document category (domain-agnostic)**  
  - **Index time:** One short LLM call per document assigns a `document_category` (e.g. receipt, permit, invoice). Stored in DB and in chunk metadata in Chroma.  
  - **Query time:** For aggregation-style questions we resolve the requested type from the user query (and conversation history for “them” / “those”). We filter retrieval by that category so context and sources contain only documents of that type.  
  - **Migration:** `alembic upgrade head` adds `document_category` to `indexed_documents`. Existing docs get a category on re-index.

- **Streaming chat**  
  Chat and streaming APIs with session and message persistence; optional tenant/directory isolation.

- **Incremental updates**  
  File changes can trigger chunk diff and incremental re-index (Phase 3 style) so the index stays in sync with the folder.

---

## Docs (selected)

| Doc | Description |
|-----|-------------|
| [docs/RAG_ACCURACY_AND_SOURCES.md](docs/RAG_ACCURACY_AND_SOURCES.md) | Why accuracy and source list were improved; document category at index time and filtering at query time. |
| [docs/RAG_AGGREGATION_AND_CONTEXT.md](docs/RAG_AGGREGATION_AND_CONTEXT.md) | Aggregation-style queries, per-doc context cap, and fitting more docs in context. |
| [docs/LLM_PROVIDERS_AND_GROQ.md](docs/LLM_PROVIDERS_AND_GROQ.md) | Switching LLM provider (Ollama / Groq / Gemini) and Groq limits. |
| [docs/LLM_PROVIDER_ADAPTERS.md](docs/LLM_PROVIDER_ADAPTERS.md) | Provider adapters for input/output limits and truncation. |
| [docs/STREAMING_CHAT_API.md](docs/STREAMING_CHAT_API.md) | Streaming chat API contract. |

---

## Running

- **Backend:** `cd ai && uvicorn main:app --reload` (default port 8000).
- **Frontend (web):** `npm run dev`.
- **Frontend (desktop):** `npm run dev:tauri`.

Point the app at a directory to index; then ask questions in chat. For consistent “list all X” and “total value of X” answers, run the migration and re-index so documents get a `document_category`.
