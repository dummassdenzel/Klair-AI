Token Optimization Refactor Plan

---

**Phase T.1 — Remove LLM Query Expansion** ✅ (done)

Goal

Eliminate the extra LLM call used for query expansion.

Your system already uses:

hybrid search (semantic + BM25)

reranking

These already provide strong recall, so LLM expansion adds little benefit but significant tokens.

Changes
Remove query_expander.py

Delete:

ai/services/query_expander.py
expand_query_for_retrieval()
Update run_tool_search_documents

Replace:

query
→ expand_query_for_retrieval
→ [variant1, variant2, variant3]
→ retrieve each
→ merge

with:

query
→ retrieve once
New flow
search_documents(query)
   ↓
_retrieve_and_build_context(query)
Expected benefits
Metric	Before	After
LLM calls	2	1
retrieval passes	3	1
tokens	high	lower
latency	higher	lower

This is a major simplification.

**Phase T.2 — Reduce Retrieval Context Size** ✅ (done)

Goal

Reduce the number of chunks sent to the LLM.

Currently your config suggests something like:

top_k=60
rerank_top_k=20
final_top_k=20

This can produce 8k–12k tokens of context.

New retrieval configuration

Update query_config.py.

top_k = 40
rerank_top_k = 12
final_top_k = 5
Reasoning
Step	Reason
top_k	maintain high recall
rerank_top_k	reduce rerank cost
final_top_k	keep only best chunks
Expected token reduction
20 chunks → 5 chunks

Context tokens:

~10k → ~3k

**Phase T.3 — Context Compression (Safe Version)** ✅ (done)

Goal

Reduce the size of retrieved context before sending it to the answer model by extracting only the relevant portions of each chunk.

Unlike summarization, this step performs relevance extraction, not paraphrasing. The original wording from the document must be preserved.

Benefits:

• Large reduction in context tokens
• Lower risk of Groq TPM limits
• Faster responses
• Often improves answer quality by removing noise

Expected reduction:

~700 token chunk → ~80–150 tokens

Total context example:

Before: 5 chunks ≈ 3000 tokens
After: 5 compressed chunks ≈ 600 tokens
New Service

Create:

ai/services/context_compressor.py

Primary function:

compress_chunks(question: str, chunks: List[str]) -> List[str]

Responsibilities:

Compress each retrieved chunk independently.

Preserve the original wording from the document.

Remove irrelevant sections.

Ensure that compression never removes all useful context.

The function returns a list of compressed chunks aligned with the original chunk order.

Compression Rules

Compression must follow these rules to maintain reliability.

1. Do not summarize

The compressor must extract text, not rewrite it.

Allowed:

Driver: G. Castaneda
Date: August 8, 2024

Not allowed:

The delivery was made by G. Castaneda on Aug 8.
2. Preserve identifiers and minimal context

Always keep identifiers such as:

• document titles
• headings
• section names
• filenames
• labels like "Invoice", "Delivery Information"

Example:

Original chunk:

Bring-in Permit

Delivery Information
Date: August 8, 2024
Driver: G. Castaneda
Helper: L. Diaz
Plate: AMA2184

Compressed chunk:

Delivery Information
Date: August 8, 2024
Driver: G. Castaneda
3. Never return an empty chunk without fallback

If compression returns nothing or extremely little text, fall back to part of the original chunk.

Example safeguard:

if compressed_length < MIN_CHARS:
    use original chunk (truncated)

This prevents accidental loss of evidence.

4. Cap maximum compressed size

To guarantee token savings, compressed chunks should be capped.

Example:

MAX_COMPRESSED_CHARS = 400
5. Only compress when needed

Compression should only run when the total context is large.

Example rule:

if total_context_chars < 2000
    skip compression

This avoids unnecessary LLM calls.

Prompt

Use a small model (Ollama or inexpensive Groq model).

Example prompt:

You are compressing document text for a retrieval system.

Given the question and document text, extract only the parts that are useful for answering the question.

Rules:
- Keep original wording from the document.
- Do not summarize or paraphrase.
- Preserve important identifiers such as headings or document labels.
- Keep minimal surrounding context if needed for clarity.
- If nothing in the text is relevant, return an empty string.

Question:
{question}

Document text:
{chunk}

Return only the relevant excerpts from the document.
Integration

Insert the compression step after retrieval and reranking, but before context construction.

Current pipeline:

retrieve
→ build_context
→ answer model

New pipeline:

retrieve
→ rerank
→ file-diversity selection
→ compress_chunks
→ build_context
→ answer model

Important:

Compression must run after reranking, since rerankers depend on the full chunk text.

When Compression Is Skipped

Compression should not run in the following cases:

• Context already small
• search_specific_document queries (optional but recommended)
• Fewer than 2 chunks retrieved

This avoids unnecessary LLM calls.

Expected Results

Example chunk:

700 tokens → ~100 tokens

Example RAG context:

Before: 3000 tokens
After: 500–700 tokens

Impact:

• Major reduction in TPM usage
• Lower latency
• Improved Groq reliability on the free tier

Reliability Safeguards

To ensure compression does not harm answers:

Extraction only (no summarization)

Preserve identifiers and headings

Fallback to original chunk when compression removes too much

Cap compressed chunk size

Skip compression for small contexts

With these safeguards, compression typically improves answer quality because irrelevant text is removed.

Phase T.4 — Limit Conversation History
Goal

Prevent conversation history from growing indefinitely.

Large histories consume tokens rapidly.

Add history limit

Inside your prompt builder.

MAX_HISTORY_MESSAGES = 2

Only include:

last user message
last assistant message
Example

Instead of sending:

10 messages

send:

2 messages
Expected token reduction
2000 tokens → 400 tokens
Phase T.5 — Chunk Truncation
Goal

Prevent extremely long chunks from entering context.

Add chunk cap

Before building context:

MAX_CHUNK_CHARS = 800

Example:

chunk = chunk[:MAX_CHUNK_CHARS]
Reason

Often the first section of a chunk contains the relevant information.

Token reduction
1000 tokens → ~250 tokens
Phase T.6 — Strong Chunk Deduplication
Goal

Prevent duplicate or overlapping chunks from appearing in context.

Your current dedupe uses:

first 400 chars

Replace with hash-based dedupe.

Example
seen = set()

for chunk in chunks:
    key = hash(chunk[:600])
    if key not in seen:
        seen.add(key)
        keep chunk
Result

Removes overlapping chunks across retrieval.

Token reduction:

10–30%
Phase T.7 — Prevent Context Explosion
Goal

Guarantee context never exceeds provider limits.

Add hard context cap

Before sending prompt:

MAX_CONTEXT_CHARS = adapter.get_max_context_chars()

If exceeded:

truncate oldest chunks
This prevents errors like
Request too large for model

which you already encountered.

Phase T.8 — Retrieval Failure Handling
Goal

Avoid sending empty context to the LLM.

Currently this can produce hallucinated answers.

Add guard

If retrieval returns no chunks:

"I couldn't find information about that in the documents."

instead of calling the answer LLM.

Phase T.9 — Greeting / Empty Message Short-Circuit
Goal

Avoid unnecessary LLM calls.

Add early exit

Before agent loop:

if router.resolve(question) in [GREETING, GENERAL]:
    return generate_simple_response()

Also normalize whitespace.

question = question.strip()

If empty:

return greeting
Expected Impact

Estimated improvements.

Metric	Before	After
tokens per query	~12k–15k	~3k–5k
LLM calls	2–3	1
latency	~2–3s	~1–2s
rate-limit failures	frequent	rare
Final Architecture After Optimization

Your pipeline becomes:

User question
   ↓
rewrite pronouns
   ↓
router
   ↓
tool selection
   ↓
hybrid retrieval
   ↓
rerank
   ↓
context compression
   ↓
dedupe
   ↓
answer generation

Key improvements:

no query expansion
smaller context
compressed chunks
limited history
Result

Your system will still have:

tool calling

hybrid retrieval

reranking

query rewriting

planner fallback

But with much lower token usage and faster responses.