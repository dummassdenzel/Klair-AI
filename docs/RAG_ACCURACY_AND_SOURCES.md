# Why the AI Still Misses Accuracy and Shows Irrelevant Sources

## What’s wrong

1. **Answers are sometimes wrong or incomplete** — e.g. “What are our delivery receipts?” lists the wrong docs or misses some.
2. **Sources don’t match the answer** — we show 40+ “sources” while the model’s answer only uses a dozen; many listed sources are irrelevant.

## Root causes (in the pipeline)

### 1. We only do **ranking**, not **filtering by document type**

- **Today:** For “what are our X?” we run **semantic + BM25 retrieval** on the user query. That returns the **top‑k most similar chunks** (by embedding + keywords). We then group by file and send up to N files (e.g. 50) to the LLM.
- **Gap:** “Give me all documents of type X” is a **filter** (documents where type = X), not a **ranking** (most similar to “X”). We have **no stored notion of document type** (invoice, permit, receipt, report, etc.). So we cannot “only retrieve delivery receipts.” We retrieve “whatever is most similar to the query,” which mixes real delivery receipts with permits that mention “delivery receipt,” and other noise.
- **Effect:** The model gets a large, noisy context and is asked in the prompt to “only list documents whose primary purpose is X.” That’s brittle: the model can misclassify, and irrelevant docs still appear in the **sources** list because we sent them.

### 2. **Sources = everything we sent in context**

- **Today:** `sources` is the list of **all files** we included in the RAG context (after top‑k and source_limit). We do not distinguish “documents the model actually used” from “documents we threw in.”
- **Effect:** The UI correctly shows “these are the files we sent to the model,” but the user expects “these are the files the model used for the answer.” So we show 46 sources when only ~12 are relevant, which looks wrong and undermines trust.

### 3. **No document-type metadata at index time**

- **DB:** `IndexedDocument` has `file_type` = **file extension** (pdf, xlsx), not semantic category.
- **Vector store:** Chunk metadata has `file_path`, `file_type` (extension), `chunk_id`, etc. — again no “document category.”
- So we **cannot** at query time say “only get chunks from documents where category = delivery_receipt.” We can only “get chunks most similar to this query,” which is the wrong primitive for “only relevant documents.”

---

## What would fix it (structural, domain-agnostic)

### A. Add document category at index time (main fix)

- **Idea:** When we index a document, assign a **document_category** (or **document_type**) that describes its primary purpose: e.g. “invoice”, “permit”, “receipt”, “report”, “form”, “contract”. Domain-agnostic labels; no hardcoding of your current doc set.
- **Where:** Store it in:
  - **DB:** Add a nullable `document_category` (or similar) column to `IndexedDocument`, and optionally keep it in sync with the vector store.
  - **Vector store:** Add `document_category` to chunk metadata when upserting, so retrieval/filtering can use it.
- **How to set it:** Either:
  - **Lightweight LLM pass:** Once per document (e.g. on first chunk or on `content_preview`), ask: “What is the primary type of this document in one word or short phrase (e.g. invoice, permit, receipt, report, form)?” and store the answer; or
  - **Heuristics:** Infer from filename patterns or first N characters if you want to avoid an LLM call (less accurate but no extra cost).
- **At query time:** For questions like “what are our X?” or “total value of all X?”:
  - **Option 1 (filter-first):** Detect requested type “X” from the query (e.g. “delivery receipts” → category “receipt” or “delivery_receipt”). Fetch **only** chunks (or only file_paths) where `document_category` matches (e.g. Chroma `where` filter), then build context from those. So the model **only** sees relevant docs, and **sources = only those docs**.
  - **Option 2 (retrieve then filter):** Retrieve as now, then **filter** the retrieved file list by `document_category` before building context; drop files that don’t match. Again, context and sources stay aligned and relevant.

Then:
- **Accuracy** improves because the model only sees documents of the requested type.
- **Sources** are correct because we only send (and thus only show) documents of that type.

### B. Optionally: sources = “documents the model cited”

- **Idea:** After the model answers, parse the response for `[Document: filename.ext]` (or your citation format) and set **sources** to only those files. So “sources” = “what the model used” instead of “what we sent.”
- **Pros:** No schema change; can improve perceived relevance of the source list.
- **Cons:** Parsing is brittle; the model might not cite every used doc or might cite wrong; we’d still be sending irrelevant docs in context, so answers could stay noisy. So this is a **UX improvement on top of** fixing context (A), not a replacement.

### C. Keep prompts domain-agnostic

- Instructions like “only list documents whose primary purpose is the requested type” are good as a **safety net** once we have filtering. They are not a substitute for actually filtering context by document type; without (A), the model will keep seeing irrelevant docs and sources will stay wrong.

---

## Recommended order of work

1. **Add `document_category` at index time** (DB + vector metadata), populated by a single LLM call per doc (or heuristics) with generic labels.
2. **For “all X” / “total of X” queries:** Detect requested category from the query; filter retrieval (or filter after retrieval) by `document_category` so context and sources contain only relevant documents.
3. **Optionally:** Add “sources = cited documents only” by parsing the model reply, as a UX improvement on top of (1)–(2).

This keeps the system **domain-agnostic** (any corpus, any labels) and fixes both **accuracy** and **relevant-only sources** at the pipeline level instead of with prompt-only tweaks.

---

## Implementation status

- **DB:** `IndexedDocument.document_category` added; migration `b7c8d9e0f1a2_add_document_category.py`. Run: `alembic upgrade head` from the `ai` directory.
- **Index time:** On index (and on each update), a single LLM call classifies the document from its content preview; the result is stored in the DB and in each chunk’s metadata in the vector store.
- **Query time:** For aggregation-style queries (“what are our X?”, “total value of X”), we resolve the requested type from the user question against distinct categories in the index, then filter retrieval by `document_category` (Chroma `where` + BM25 restricted to those file paths). Context and sources then contain only documents of that type.
- **Existing documents:** Have `document_category` null until re-indexed. Re-index (e.g. re-add the directory or touch files) to backfill categories; until then, category filtering only applies to newly indexed or updated docs.
