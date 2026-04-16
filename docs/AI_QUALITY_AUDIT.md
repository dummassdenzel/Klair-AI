# AI Quality Audit — Klair AI RAG System

**Date:** April 2026  
**Auditor:** AI Engineer (systematic review)  
**Scope:** Embedding pipeline, retrieval configuration, reranker, LLM generation, structured data, query routing  
**Status of each item:** `[ ]` Pending · `[~]` In Progress · `[x]` Done

---

## Bug / Design Flaw Glossary

These are the formal engineering names for the classes of problems found in this system.

| Term | Meaning |
|---|---|
| **Stochastic inference on a deterministic task** | Using a high temperature (0.7) for factual document retrieval, causing the same question with the same context to produce different answers on consecutive runs |
| **Query intent misrouting** | The classifier assigns a query to the wrong pipeline (e.g. a counting query routed to chunk-based search instead of document enumeration) |
| **Retrieval-induced non-determinism** | The combination of probabilistic retrieval (different chunks per run) and high temperature means the LLM context window changes every query, producing different outputs |
| **Agentic intent collapse** | An LLM agent always falls back to its most familiar tool regardless of the task — here the Groq agent defaulting to `search_documents` for counting queries |
| **Information compression loss** | Tool result serialization strips content previews, leaving the LLM unable to categorize documents from filenames alone |
| **Domain mismatch (embedding)** | The embedding model was trained on general web corpus, producing undifferentiated vectors for logistics business documents |
| **API misuse (BGE prefix)** | The BGE model family requires a query instruction prefix that the code omits, degrading similarity scores by 5–15% |
| **Domain mismatch (reranker)** | MS MARCO cross-encoder trained on web search produces near-zero discriminative scores on business documents, adding latency with no quality improvement |
| **Modality mismatch** | A prose-based token chunker applied to tabular spreadsheet data destroys row structure, causing incomplete numerical extraction |
| **Context window under-utilization** | Only ~12% of the available LLM context window is used due to undersized `final_top_k` and a `max_chunks_per_file` cap |

---

## Phase Overview

| Phase | Title | Items | Priority |
|---|---|---|---|
| 1 | Non-Determinism Fixes | 1.1 | Critical |
| 2 | Embedding Pipeline Overhaul | 2.1, 2.2 | Critical |
| 3 | Reranker Overhaul | 3.1 | High |
| 4 | Retrieval Parameter Tuning | 4.1, 4.2 | High |
| 5 | Structured Data Extraction Overhaul | 5.1 | High |
| 6 | Query Routing Fixes | 6.1 | Medium |
| 7 | LLM Service Fixes | 7.1, 7.2 | Medium |

---

## Phase 1 — Non-Determinism Fixes

### 1.1 — Lower RAG Temperature from 0.7 to 0.1

| | |
|---|---|
| **Status** | `[✅]` |
| **Severity** | Critical |
| **Type** | Stochastic inference on a deterministic task |
| **File** | `ai/services/document_processor/llm/llm_service.py` |

**Problem:**  
All RAG generation calls (`generate_response()` and `generate_response_stream()`) hard-code `temperature=0.7`. This setting is correct for creative writing. For factual document retrieval it directly causes non-determinism: the model samples probabilistically from its output distribution, so it can and will count the same document list differently on consecutive calls.

Evidence from the user's session: asking "how many delivery receipts" twice returned "11" then "8". Temperature is a significant contributing factor alongside retrieval variance.

Industry standard for RAG is **0.0–0.2**.

**Affected code locations:**

```python
# generate_response() — Ollama path, ~line 215
"options": { "temperature": 0.7, ... }

# generate_response() — Groq path, ~line 195
completion = await self._groq.chat.completions.create(
    ...temperature=0.7...
)

# generate_response() — Gemini path, ~line 175
generation_config = {"temperature": 0.7, ...}

# generate_response_stream() — same three paths, same values
```

**Fix:**  
Change `temperature=0.7` → `temperature=0.1` in all RAG generation calls (both `generate_response` and `generate_response_stream` for all three providers). The planner and tool-calling paths already correctly use `temperature=0.1`.

**What does NOT need to change:** `generate_simple()` planner calls already use `temperature=0.1`. `chat_with_tools()` already uses `temperature=0.1`. Only the final RAG answer generation paths need this fix.

---

## Phase 2 — Embedding Pipeline Overhaul

> **Note:** Both items in this phase require re-embedding the entire document corpus after the code changes. After applying 2.1 and 2.2, clear the ChromaDB collection and re-index all documents.

### 2.1 — Upgrade Embedding Model from bge-small to bge-base

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | Critical |
| **Type** | Domain mismatch (embedding) — model-data mismatch |
| **File** | `ai/config.py`, `ai/services/document_processor/extraction/embedding_service.py` |

**Problem:**  
`BAAI/bge-small-en-v1.5` is a 33M parameter model producing 384-dimensional vectors, trained on a general English corpus. The documents in this system are business logistics files with specialized vocabulary: BIP permit codes (`BIP-25-0011932`), internal document IDs (`GUA04`, `TCO002`, `PES005`), currency values (`Php 1,134,913.50`), and domain-specific terminology (export declarations, packing lists, certificate of registration).

The embedding model has no representation for this vocabulary. The practical consequence is that cosine similarity scores cluster near each other across all chunks — every chunk looks equally (un)related to the query — which starves the downstream RRF fusion and reranker of meaningful signal.

**Comparison:**

| Model | Params | Dimensions | BEIR Avg Score | Notes |
|---|---|---|---|---|
| `BAAI/bge-small-en-v1.5` (current) | 33M | 384 | 51.68 | Too small for domain docs |
| `BAAI/bge-base-en-v1.5` (recommended) | 109M | 768 | 53.25 | Same API, 2× dimensions |
| `BAAI/bge-large-en-v1.5` (premium) | 335M | 1024 | 54.29 | Slower, best quality |

**Fix:**  
Change default in `config.py`:
```python
EMBED_MODEL_NAME: str = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-base-en-v1.5")
```

**Post-change requirement:** Clear ChromaDB collection and BM25 index, then re-index all documents.

---

### 2.2 — Add BGE Query Instruction Prefix

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | Critical |
| **Type** | API misuse (BGE prefix) |
| **File** | `ai/services/document_processor/extraction/embedding_service.py`, `ai/services/document_processor/retrieval_service.py` |

**Problem:**  
The BGE model family uses **asymmetric encoding**: documents are encoded as-is, but queries must be prefixed with a specific instruction string. From the official BAAI documentation:

> For `bge-*-en-v1.5`, queries should use the prefix:  
> `"Represent this sentence for searching relevant passages: "`  
> Documents should be encoded without any prefix.

The current code encodes queries identically to documents — no prefix is applied anywhere. This reduces query-document similarity scores by an estimated 5–15%, meaning the ranking of retrieved chunks is less accurate than it should be.

**Affected code:**
```python
# embedding_service.py — used for both queries and documents
def encode_single_text(self, text: str) -> List[float]:
    return self.encode_texts([text])[0]
```

**Fix:**  
Add a `encode_query(text)` method to `EmbeddingService` that applies the BGE prefix for query-side embeddings only. Update all query embedding call sites in `retrieval_service.py` to use `encode_query()` instead of `encode_single_text()`.

```python
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

def encode_query(self, text: str) -> List[float]:
    """Encode a search query with the BGE instruction prefix."""
    prefixed = BGE_QUERY_PREFIX + text if "bge" in self.model_name.lower() else text
    return self.encode_single_text(prefixed)
```

Document encoding (`encode_texts()`) does NOT get the prefix.

**Post-change requirement:** Re-embed all documents (same re-index as 2.1).

---

## Phase 3 — Reranker Overhaul

### 3.1 — Replace or Disable the MS MARCO Cross-Encoder

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | High |
| **Type** | Domain mismatch (reranker) — negative ROI component |
| **File** | `ai/services/document_processor/retrieval/reranker_service.py`, `ai/config.py` |

**Problem:**  
`cross-encoder/ms-marco-MiniLM-L-6-v2` was trained on MS MARCO, a web search dataset. Its training distribution contains web pages and search queries. The system is using it to rerank Philippine logistics documents.

Evidence from the production logs:
```
Re-ranked 57 -> top 50 (avg rerank score: 0.003)
Re-ranked 54 -> top 50 (avg rerank score: 0.001)
```

MS MARCO cross-encoders output raw logits, which are converted to probabilities via sigmoid. Scores of 0.001–0.003 map to approximately sigmoid(-7) to sigmoid(-6) — the model is treating every document as nearly maximally irrelevant. **The reranker provides zero discriminative signal for this document domain.**

Concrete costs:
- 3–8 seconds of CPU/GPU compute per query (running a cross-encoder on 54–60 document pairs)
- Zero improvement in result ordering
- The final ranked list is essentially the RRF-fused order, not the reranked order

**Two options:**

**Option A (immediate, zero-cost) — Disable reranking:**  
Set `rerank_top_k = 0` for all query types in `RetrievalConfig`. The `_retrieve_chunks()` method already skips the reranker when `rerank_top_k == 0`. This recovers 3–8s per query with no quality loss in the current domain.

**Option B (proper fix) — Replace with a better model:**  
`cross-encoder/ms-marco-MiniLM-L-12-v2` is a 12-layer variant that is somewhat more robust to out-of-domain text. Alternatively, `BAAI/bge-reranker-base` is explicitly trained as a retrieval reranker (same BAAI family as the embedding model) and is a better architectural choice for this pipeline.

**Recommendation:** Apply Option A immediately as a hotfix (recover 3–8s latency), then evaluate Option B as a proper replacement once the embedding model upgrade in Phase 2 is complete.

---

## Phase 4 — Retrieval Parameter Tuning

### 4.1 — Increase `final_top_k` and `max_chunks_per_file` for Standard Queries

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | High |
| **Type** | Context window under-utilization |
| **File** | `ai/services/document_processor/query_config.py` |

**Problem:**  
The current `comprehensive` (standard document search) parameters:

```python
comprehensive_top_k: int = 40          # retrieve 40 chunks
comprehensive_rerank_top_k: int = 12   # rerank 12 of them
comprehensive_final_top_k: int = 5     # pass 5 to the LLM
max_chunks_per_file: int = 2           # hard cap: ≤2 chunks per any file
```

With `chunk_size=300` tokens, 5 chunks = ~1,500 tokens of context. Groq's llama-4-scout has a 128,000-token context window. `GROQ_MAX_CONTEXT_CHARS = 50,000` chars ≈ 12,500 tokens. We are using **~12% of available context** for standard queries.

`max_chunks_per_file = 2` is the more damaging limit: a delivery receipt might span 8 chunks. If the total value is in chunk 3 and the line items are in chunks 4–6, none of them make it to the LLM.

**Fix (suggested values):**

```python
comprehensive_top_k: int = 40           # unchanged
comprehensive_rerank_top_k: int = 20    # rerank more candidates
comprehensive_final_top_k: int = 12     # pass 12 to the LLM (~3,600 tokens)
max_chunks_per_file: int = 4            # allow 4 chunks per file
```

This still uses only ~29% of the Groq context window but significantly improves coverage for multi-chunk documents.

---

### 4.2 — Tighten `is_aggregation_query` Heuristic

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | Medium |
| **Type** | Regex over-trigger (false positives) |
| **File** | `ai/services/document_processor/query_config.py` |

**Problem:**  
Current patterns fire aggregation mode (top_k=100, 8s reranking) on unrelated queries:

```python
if re.search(r"what\s+are\s+our\s+\w+", q):    # "what are our options" → AGGREGATION!
    return True
if re.search(r"which\s+(are\s+)?(our\s+)?\w+", q):  # "which file?" → AGGREGATION!
    return True
```

Any question containing "what are our [word]" or "which [word]" triggers the expensive high-recall path, adding unnecessary latency.

**Fix:**  
Restrict to explicit numerical/exhaustive intent signals only:

```python
# Keep these (correct):
if re.search(r"total\s+(value\s+)?of\s+(all\s+)?", q): return True
if re.search(r"sum\s+of\s+(all\s+)?", q): return True
if re.search(r"list\s+all\s+", q): return True

# Replace the broad patterns with tighter ones:
if re.search(r"(total|combined|aggregate|overall)\s+(value|amount|cost|sum)", q): return True
if re.search(r"add\s+(up|together)\s+all", q): return True
# Remove the "what are our X" and "which X" patterns entirely
```

---

## Phase 5 — Structured Data Extraction Overhaul

### 5.1 — Separate Extraction Pipeline for Tabular Files (XLS/XLSX)

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | High |
| **Type** | Modality mismatch — prose chunker applied to tabular data |
| **File** | `ai/services/document_processor/extraction/` (new extractor needed) |

**Problem:**  
The `DocumentChunker` is a generic sentence/paragraph splitter. It splits text at sentence boundaries, targeting 300-token windows. When an XLS/XLSX file is extracted to plain text, a financial table like:

```
GUA04  Delivery Receipt  Aug 23 2025  Php 1,775,767.50
TCO002  Delivery Receipt  Sep 01 2025  Php 354,632.00
PES007  Delivery Receipt  Oct 02 2025  Php 790,967.00
```

...gets split mid-table when the chunk boundary fires. With `max_chunks_per_file = 2` (before Phase 4.1 fix), only rows from 2 chunks are seen by the LLM. This directly causes wrong totals on financial aggregation queries.

This is an **architectural mismatch**, not a configuration problem. The chunker is working correctly for its design purpose (prose). Spreadsheets require a fundamentally different extraction strategy.

**Required overhaul:**  
Build a `SpreadsheetExtractor` that:
1. Extracts data per sheet, per row group (do not mix sheets in one chunk)
2. Preserves column headers with every row (or row group) for context
3. Groups rows into chunks based on row count, not token count — ensuring a logical table unit (e.g. all rows with the same document type) stays together
4. Stores a chunk header like `[Sheet: Sheet1, Rows: 1-20]` in the metadata so retrieval can reconstruct the full table

Until this overhaul is done, aggregation queries over spreadsheet data will produce unreliable totals.

---

## Phase 6 — Query Routing Fixes

### 6.1 — Tighten Planner Token Limit and Log Fallback

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | Medium |
| **Type** | Output truncation — silent failure |
| **File** | `ai/services/document_processor/query_pipeline.py` |

**Problem:**  
`PLANNER_MAX_TOKENS = 400`. The planner generates JSON like:

```json
{"tools": [{"tool": "search_documents", "query": "total value of all delivery receipts from August to October 2025 including BIP permits"}]}
```

A long query string in the JSON can reach or exceed 400 tokens on verbose queries. When truncated, `_parse_planner_output()` receives invalid JSON, returns `None`, and falls back to the classifier's safe default — `search_documents` with the raw user question — **without logging why the fallback fired**. This silent override means planner failures are invisible in production logs.

**Fix:**  
1. Raise `PLANNER_MAX_TOKENS = 400` → `600`
2. In `_pipeline_planner()`, add a `logger.warning("Planner output invalid JSON; falling back to classifier default")` before the fallback is invoked

---

## Phase 7 — LLM Service Fixes

### 7.1 — Fix Gemini Streaming (Currently Blocking / Non-Streaming)

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | Medium |
| **Type** | Interface contract violation — blocking call in async stream |
| **File** | `ai/services/document_processor/llm/llm_service.py` |

**Problem:**  
`generate_response_stream()` for the Gemini provider runs:

```python
result = await asyncio.to_thread(self._gemini.generate_content, prompt, ...)
# ... then yields the full text as a single chunk
yield text
```

`generate_content()` is a blocking synchronous call that waits for the complete response. The method wraps it in `asyncio.to_thread()` to avoid blocking the event loop, but the user experience is: full wait, then entire response appears at once. There is no streaming. The Gemini Python SDK (`google-generativeai >= 0.3`) supports true streaming via `generate_content(..., stream=True)` with an async iterator.

**Fix:**  
Replace the `asyncio.to_thread(generate_content, ...)` call with the async streaming API:

```python
response = await asyncio.to_thread(
    self._gemini.generate_content, prompt,
    generation_config=generation_config,
    stream=True
)
for chunk in response:
    delta = getattr(chunk, "text", None) or ""
    if delta:
        yield delta
```

Note: the `google-generativeai` SDK's streaming iterator is synchronous, so it still runs via `asyncio.to_thread` wrapping the iteration, but chunks are yielded progressively rather than all at once.

---

### 7.2 — Remove Deprecated `update_model()` / `update_base_url()` Methods

| | |
|---|---|
| **Status** | `[ ]` |
| **Severity** | Low |
| **Type** | Dead code / API confusion |
| **File** | `ai/services/document_processor/llm/llm_service.py` |

**Problem:**  
`LLMService` has two legacy methods:

```python
def update_model(self, new_model: str): ...
def update_base_url(self, new_url: str): ...
```

These predate `switch_provider()` which was added in this audit cycle. They only update Ollama-specific attributes and do not update the adapter or reset cached clients. Any caller using them for Gemini or Groq configuration gets silently incorrect state. They are not called anywhere in the codebase.

**Fix:**  
Remove both methods. `switch_provider()` is the correct runtime API.

---

## Progress Tracker

| Item | Description | Status | Notes |
|---|---|---|---|
| 1.1 | Lower RAG temperature 0.7 → 0.1 | `[x]` | Fixed in llm_service.py + configurable via Settings UI |
| 2.1 | Upgrade embedding model to bge-base | `[ ]` | Requires full re-index |
| 2.2 | Add BGE query instruction prefix | `[ ]` | Requires full re-index |
| 3.1 | Disable or replace MS MARCO reranker | `[ ]` | Option A: disable (immediate); Option B: replace |
| 4.1 | Increase final_top_k and max_chunks_per_file | `[ ]` | Config values only |
| 4.2 | Tighten is_aggregation_query patterns | `[ ]` | Remove broad regexes |
| 5.1 | Spreadsheet tabular extraction pipeline | `[ ]` | Full overhaul — new extractor module |
| 6.1 | Raise planner token limit + log fallback | `[ ]` | Small change |
| 7.1 | Fix Gemini streaming | `[ ]` | Refactor generate_response_stream() |
| 7.2 | Remove deprecated update_model/update_base_url | `[ ]` | Delete 2 methods |

---

## Re-indexing Note

Items **2.1** and **2.2** both require a full re-embed of the document corpus because they change the embedding space. Perform them together in a single re-index pass:

1. Apply code changes for 2.1 (model name) and 2.2 (query prefix method)
2. Stop the server
3. Delete `./chroma_db/` directory and `./chroma_db/bm25_index.pkl` / `bm25_documents.pkl`
4. Restart the server and re-set the document directory to trigger re-indexing

Do not apply 2.1 without 2.2 or vice versa — the query and document embeddings must be from the same model with the same encoding convention.
