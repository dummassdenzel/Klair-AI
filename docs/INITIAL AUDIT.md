AI Pipeline Audit — Klair AI
I'll be direct and systematic. The application has a working RAG skeleton with some genuinely thoughtful pieces, but it also carries a set of real architectural problems, correctness bugs, and design decisions that will cause increasing pain at scale or with more complex queries.
1. The Orchestrator Is a God Object
orchestrator.py is 2,280+ lines containing: file indexing, directory scanning, retrieval, tool dispatch, planner logic, agent loop, context compression, conversation history management, statistics, cleanup, and SSE event generation. This violates the Single Responsibility Principle aggressively.
The immediate consequence is the most glaring code problem in the codebase:
query() and query_stream() are nearly identical. The same logic — tool loop → planner fallback → legacy classifier — is duplicated in two separate methods. Same for _query_via_tool_loop / _query_stream_via_tool_loop and _query_via_planner_fallback / _query_stream_via_planner_fallback. You have essentially four methods doing the same work in two pairs, differing only in whether they yield SSE events. If a bug exists in one path, it likely exists in the other. Any future change must be made four times.
2. BM25 Hybrid Search — Built but Not Actually Fused
HybridSearchService with proper Reciprocal Rank Fusion (RRF) is implemented and instantiated in the orchestrator. It is never called during query time.
Instead, _retrieve_chunks() manually fetches semantic results and BM25 results in parallel, then applies a score "boost" by adding a flat constant (retrieval_config.bm25_boost) to the semantic score of chunks that BM25 also found:
This is not hybrid fusion. It is "confirm semantic results with keyword search and bump their score." A document that ranks #1 in BM25 but #20 in semantic gets no benefit unless it appears in the semantic results first. The HybridSearchService.fuse_results() RRF implementation was written, then not wired in. The existing fusion logic does not leverage keyword search for recall expansion.
3. The Relevance Score Is Broken
In _retrieve_and_build_context:
The avg_score here is a cosine similarity value on [0, 1]. Multiplying by 50 and clamping to 1.0 means that any document with a cosine similarity above 0.02 will show as 100% relevant. The number 50 is a magic number with no documented basis. All meaningful signal in the score is compressed into a tiny range near 0. The scores shown to users in the source panel are not meaningful and cannot be used to threshold quality.
4. Metadata-First Indexing Has a Hash Format Bug
During the metadata phase (_build_metadata_index), the stored hash is:
During content indexing (add_document), the real hash is:
These are different formats (path:mtime string vs MD5/SHA hex). The check if stored_hash == current_hash will always be False for every file during initial content indexing, meaning the incremental-update optimization is bypassed entirely for first-time indexing. Every file is re-read and re-embedded regardless. This is likely invisible in development but is a correctness problem: the system believes it is skipping unchanged files when it is not.
5. BM25 Is Not Persisted — Keyword Search Silently Fails on Restart
BM25 is built in memory and populated during indexing. If the application restarts, the SQLite database shows all files as "indexed", but the BM25 index is empty. The startup _load_existing_metadata reloads the filename trie and the LRU metadata cache from the DB, but does not rebuild the BM25 index. Keyword search will contribute nothing until background content re-indexing completes, but the system does not re-index files it considers already indexed (hash matches). The practical result is that after a restart, BM25 is permanently empty until files change.
6. Character-Count Chunking, Not Token-Count Chunking
DocumentChunker chunks by character length (chunk_size=1000). LLMs, embedding models, and context windows are all measured in tokens, not characters. At 4 characters per token on average, 1000 characters is roughly 250 tokens — very small. Context windows for bge-small-en-v1.5 max at 512 tokens; Groq models handle tens of thousands. The chunk size should be expressed in tokens, not characters, and should be calibrated against the embedding model's maximum input size. Chunking at 250 tokens and then reranking 20 of them gives the LLM roughly 5,000 tokens of context — reasonable but the configuration is misleading and unintuitive.
The boundary detection also has a subtle bug:
This will split on decimal points (3.14), URL dots (www.example.com), abbreviations (e.g., etc., Mr., U.S.A.), and any period in a filename. It will also produce incorrect boundaries in structured documents (tables, CSV-derived text, markdown headers).
7. The Planner Path Adds an Extra LLM Call for Every Query
For Ollama and Gemini users (the majority, since Groq requires an API key), every single query—including "hello"—goes through:
Planner LLM call (classify and pick tools)
Tool execution (retrieval)
Answer LLM call
That is a minimum of two LLM round trips per query regardless of query complexity. For a greeting, the planner returns {"tools": []}, then generate_response is called with an empty context. The conversation summarization adds a third call for long sessions. This is a latency problem on local Ollama, and a cost and rate-limit problem on cloud providers.
8. Query Cache Is Bypassed by the Streaming Path
From chat.py:
The cache is only used in POST /api/chat. The frontend exclusively uses POST /api/chat/stream (SSE). This means the query cache never hits in normal usage. It's dead code in practice.
Additionally, the cache is not invalidated when documents change (new file added, existing file modified). A user who indexes new documents and asks the same question will get the old cached answer.
9. asyncio.create_task() in __init__
asyncio.create_task() requires a running event loop. Calling it in __init__ — a synchronous method — is only safe if an event loop is already running in the current thread (which it is under FastAPI/uvicorn, but only at startup). If the orchestrator is ever instantiated outside an async context (e.g., in tests), this crashes. The tasks also run unobserved: if _load_existing_metadata fails, the error is logged and swallowed, and the trie is silently empty.
10. Settings Is a Plain Class, Not Thread-Safe, and Leaks Internal Config
The type annotations are class-level but the values are class-level attributes too. This means all attributes are shared across all instances. Since settings = Settings() is a singleton, mutations via settings.update() (called by POST /api/update-configuration) modify global state that is read concurrently by all in-flight requests. There is no lock. This is safe by asyncio's single-threaded nature in the FastAPI async path, but not safe if any sync threadpool tasks read settings while an update is applied.
More critically, GET /api/configuration returns OLLAMA_BASE_URL and OLLAMA_MODEL in plain text. If the endpoint were ever called from outside localhost, that would expose internal configuration. The CORS policy currently prevents this, but it is worth noting the endpoint was not designed with exposure in mind.
11. The client.ts Ignores VITE_API_BASE_URL
src/lib/config.ts defines VITE_API_BASE_URL as an overridable base URL. src/lib/api/client.ts hardcodes http://127.0.0.1:8000/api. The config value is never read by the actual HTTP client. This makes the environment variable dead configuration — a developer who follows the documentation and sets VITE_API_BASE_URL will see no effect.
12. context_compressor.compress_chunks Adds a Third LLM Call
For non-aggregation, multi-file, large-context queries on the planner path:
Planner call
Tool execution (retrieval)
compress_chunks LLM call (to extract relevant sentences from chunks)
Answer LLM call
That is potentially three LLM round trips per query. The compress step is guarded by several conditions, but they are permissive: len(documents) >= 2 and total_context_chars >= 2000. Two documents and 2,000 characters is a normal result for almost any query. Context compression with a local Ollama model (the default) will often degrade quality, not improve it, because small models are bad at identifying what is and is not relevant without understanding the query deeply.
13. Error Messages Leak Internal Detail to Callers
In chat.py:
raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
In query():
return QueryResult(message=f"Sorry, I encountered an error while processing your query: {str(e)}", ...)
Python exception messages frequently include file paths, SQL queries, model names, API endpoint details, and stack information. These are surfaced directly to the frontend. For a local desktop app the risk is low, but the pattern is incorrect.
14. No Input Validation or Rate Limiting on Chat Endpoints
POST /api/chat and POST /api/chat/stream accept arbitrary message strings with no length limit, no content validation, and no rate limiting. A very long message (e.g., 100,000 characters) will be embedded, fed to the planner, fed to the LLM, and stored in the database. For a local app this is an inconvenience; the user can exhaust Groq's TPM limit, crash an Ollama model, or fill the SQLite database with junk.
15. The HybridSearchService Class Is Dead Weight
HybridSearchService is instantiated (self.hybrid_search = HybridSearchService(k=60)) but its fuse_results() method is never called anywhere in the codebase. The orchestrator implements its own ad-hoc fusion inline in _retrieve_chunks. The class takes up space, was clearly written first, then replaced without being removed.