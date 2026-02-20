# RAG aggregation and full-context behaviour

## Problem

For questions like **"What is the total value of our delivery receipts?"** or **"List all delivery receipts"**, the model sometimes misses documents (e.g. PES01) that the user knows exist. Two causes:

1. **Retrieval is relevance-based**  
   We take top-k chunks (e.g. 60), rerank to `final_top_k` (e.g. 20), then group by file. So we only send ~20 documents to the LLM. Any document that ranks just below the cut (e.g. PES01) never appears in context.

2. **Context truncation drops documents from the end**  
   We build context as `Doc1 --- Doc2 --- ... --- DocN` and truncate to the provider limit (e.g. 50k chars) by **dropping whole documents from the tail**. Documents at the end (often lower relevance) are omitted, so the model literally never sees them.

So the model is not “forgetting” or “being dumb”—it is **not given** those documents because of retrieval and truncation.

## Approach

1. **Aggregation-style queries**  
   When the user asks for *all* of a type (“list all delivery receipts”, “total value of all delivery receipts”, “sum of …”), we need **high recall** over that type, not just top-k by relevance.

2. **Higher recall for aggregation**  
   For such queries we use:
   - Higher `final_top_k` and higher source limit so more documents are retrieved and passed to the LLM.
   - Detection is heuristic (e.g. “total value of”, “total of”, “list all … receipts”, “sum of”).

3. **Per-document context cap**  
   Instead of sending full document text and then truncating by dropping documents from the end, we **cap each document’s contribution** (e.g. first 2000–2500 chars per file). That way:
   - More documents fit in the same 50k context window.
   - No document is dropped entirely; the model gets a slice of every retrieved document.
   - For “total value” the value is usually in the first part of the doc, so a cap is sufficient.

4. **Optional future improvement**  
   For “all delivery receipts” we could do two-phase: (1) broad retrieval or DB filter to get all file paths that are delivery receipts, (2) fetch all chunks for those paths via `vector_store.get_document_chunks(file_path)` and build context from that. That would guarantee no delivery receipt is missed, at the cost of more complexity and possibly a larger context.

## Config / code touchpoints

- **Query config**: aggregation retrieval params (`aggregation_final_top_k`, `aggregation_max_sources`) and `is_aggregation_query(question)`.
- **Orchestrator**: detect aggregation, pass flag into retrieval params and source limit; when building RAG context, apply per-doc cap (e.g. `RAG_MAX_PER_DOC_CHARS` or adapter).
- **Adapter**: optional `get_max_per_doc_rag_chars()` for per-document cap (default 2500); truncation still applies to total context.
