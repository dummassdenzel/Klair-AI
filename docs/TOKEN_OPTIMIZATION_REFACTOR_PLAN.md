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

Phase T.2 — Reduce Retrieval Context Size
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
Phase T.3 — Add Context Compression
Goal

Extract only the relevant sentences from retrieved chunks before sending them to the answer model.

This reduces context size dramatically while keeping factual accuracy.

New service

Create:

ai/services/context_compressor.py
Function
compress_chunks(question: str, chunks: List[str]) -> List[str]
Prompt

Use a small model (Ollama or cheap Groq model).

Example prompt:

Given the user question and the document text,
extract only the sentences needed to answer the question.

Question:
{question}

Document text:
{chunk}

Return only the relevant lines.
If nothing is relevant, return empty.
Integration

Insert compression step in retrieval pipeline.

Current:

retrieve
→ build_context

New:

retrieve
→ compress_chunks
→ build_context
Expected results

Example chunk:

700 tokens → 50 tokens

Total context:

3500 tokens → ~500 tokens

Huge token savings.

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