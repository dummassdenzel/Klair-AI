# Streaming Chat API Design

**Purpose**: Define the API for streaming LLM responses so the client can show tokens as they arrive (faster perceived response time).

**Status**: Implemented (backend + client use streaming by default).

---

## 1. Overview

- **Endpoint**: `POST /api/chat/stream`
- **Same auth/tenant** as `POST /api/chat`: requires tenant context (directory set) and uses the same rate limiting where applicable.
- **Request body**: Identical to non-streaming — `ChatRequest`: `{ "session_id": number, "message": string }`.
- **Response**: HTTP 200 with `Content-Type: text/event-stream` (Server-Sent Events). On validation or server error before the stream starts, return normal JSON 4xx/5xx.

---

## 2. SSE Event Types

The response is a single SSE stream. Each event has an `event` name and a `data` payload (JSON).

| Event   | When sent        | Payload (JSON) |
|--------|-------------------|-----------------|
| **meta** | Once, at start   | `{ "sources": [ { "file_path", "relevance_score", "content_snippet" }, ... ], "session_id": number }` |
| **token** | Many times      | `{ "delta": " string " }` — append to the displayed message. |
| **done** | Once, at end     | `{ "message": "full response text", "response_time": number }` — canonical message for history/copy. |
| **error** | Once, on failure | `{ "detail": "error message" }` — stream stops; client should show error. |

- **meta**: Sent as soon as retrieval and (if needed) query classification are done. Sources and `session_id` allow the UI to show “Answering…” and source chips before any token. For greeting/general/document_listing flows that have no document sources, `sources` is `[]` but `meta` is still sent so the client has a consistent start.
- **token**: Each LLM chunk is sent as a **token** event. Client concatenates all `delta` values to build the in-progress message.
- **done**: After the last token (or after a single non-streamed message). `message` is the full reply; client can use it for storing in history, copying, or cache key. `response_time` is in seconds.
- **error**: If something fails after the stream has started (e.g. LLM error mid-stream), send **error** and close the stream. For failures before any event (e.g. no directory, invalid request), do not use SSE; return a normal HTTP error with JSON body.

---

## 3. Server-Side Flow

1. **Validate & resolve session**  
   Same as `POST /api/chat`: resolve or create `chat_session`, load conversation history (e.g. last N messages).

2. **Optional: cache**  
   If a response is cached for this session + message, either:
   - Skip stream and return 200 JSON (same as non-streaming), or  
   - Send **meta** (sources from cache if stored), one **token** with the full cached message, then **done**.  
   Design choice: first version can skip cache for `/api/chat/stream` to keep logic simple.

3. **Retrieval & classification**  
   Run the same pipeline as non-streaming: classify query → retrieval (semantic + BM25 + rerank) or document listing → build context and sources. No streaming yet.

4. **Start stream**  
   - Send **meta** with `sources` and `session_id`.

5. **Stream LLM**  
   Call LLM with streaming enabled; for each chunk, send **token** `{ "delta": "..." }`.

6. **Finish**  
   - Send **done** with full `message` and `response_time`.
   - Persist message and link documents (same as non-streaming): `add_chat_message`, then parallel document linking. Can be done after **done** so the client already has the full text.

7. **Errors**  
   - Before stream: return 400/500 with JSON.  
   - After stream started: send **error** event with `detail`, then close stream.

---

## 4. Client Usage

- Use `EventSource` or `fetch` with `ReadableStream` and an SSE parser (e.g. parse `event:` and `data:` lines).
- On **meta**: update UI with sources and “Answering…” state.
- On **token**: append `data.delta` to the current message and re-render.
- On **done**: set final message from `data.message`, store in local state/history, stop spinner.
- On **error**: show `data.detail`, stop spinner, treat as failed response.

Because **done** carries the full message, the client can always use that as the single source of truth for “what was said” (e.g. for copy, history, and consistency with non-streaming).

---

## 5. Backend Components to Add/Change

| Component | Change |
|-----------|--------|
| **main.py** | New route `POST /api/chat/stream` that returns `StreamingResponse(..., media_type="text/event-stream")`, runs session + retrieval, then streams meta → tokens → done and runs persistence after. |
| **Orchestrator** | New method e.g. `query_stream(question, conversation_history, ...)` that performs retrieval/classification and then yields or streams: (sources), (token chunks), (full message + response_time). Alternatively, the route can call existing `query()` logic in a “streaming” path and only stream the LLM part; then the orchestrator needs a way to return sources + context and a streaming generator. |
| **LLMService** | New method e.g. `generate_response_stream(query, context, conversation_history)` that yields text chunks (async generator). Ollama: use `stream: true` and iterate over the response stream. Gemini: use `generate_content_async` with streaming if available, or fall back to non-streaming and emit one chunk. |

---

## 6. Summary

- **Request**: Same as `POST /api/chat` (`ChatRequest`).
- **Response**: SSE stream with **meta** (sources, session_id) → **token** (delta) × N → **done** (message, response_time), or **error** (detail) on failure.
- **Caching**: Optional; first version can omit cache for the stream endpoint.
- **Persistence**: Same as non-streaming (add_chat_message + document linking), after the stream completes.

This design keeps the non-streaming `POST /api/chat` unchanged and adds a dedicated streaming endpoint. The Svelte client uses `POST /api/chat/stream` by default via `apiService.sendChatMessageStream()` and updates the message in place as tokens arrive.

### 7. Implementation summary

| Part | Location |
|------|----------|
| **LLM streaming** | `ai/services/document_processor/llm/llm_service.py` — `generate_response_stream()` (Ollama: NDJSON stream; Gemini: single chunk) |
| **Orchestrator stream** | `ai/services/document_processor/orchestrator.py` — `query_stream()` yields `meta`, `token`, `done`, `error` |
| **Route** | `ai/main.py` — `POST /api/chat/stream` returns SSE, persists after stream |
| **Client** | `src/lib/api/services.ts` — `sendChatMessageStream()`; `src/routes/+page.svelte` — uses stream and updates message on each token |
