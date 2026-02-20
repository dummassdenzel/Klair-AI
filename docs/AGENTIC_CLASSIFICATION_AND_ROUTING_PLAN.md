# Agentic Classification + Routing — Plan

This document plans the **classification + routing** agentic layer for Klair: how it affects code structure, where it lives, and how to start.

---

## 1. Current State (Summary)

| Component | Location | Behavior |
|-----------|----------|----------|
| **Classification** | `orchestrator.py`: `_classify_query`, `_classify_query_fast_path`, `_classification_cache_key` | Returns one of: `greeting`, `general`, `document_listing`, `document_search`. Uses fast path (greeting only), LRU cache, then LLM. |
| **Dispatch** | Same file: `query()` and `query_stream()` | After classification, branches: greeting/general → `_generate_direct_response`; document_listing → `_get_document_listing`; document_search → `_retrieve_chunks` + LLM. |
| **Config** | `query_config.py` | `RetrievalConfig.get_retrieval_params(query_type)`, `get_source_limit(query_type, has_selected_files)`. |
| **API** | `main.py` | Calls `ctx.doc_processor.query_stream(...)`, uses `query_type` from stream for metrics and logging. |
| **Schemas** | `schemas/chat.py`, `models.py` | `ChatRequest`, `QueryResult.query_type`. No explicit “route” or “tool” type yet. |

Classification is **inside** the orchestrator and tightly coupled. Adding new routes (e.g. “write_file”, “summarize_to_doc”) would mean more branches in the same big methods. The goal is to make routing explicit and extensible.

---

## 2. Goal: Agentic Classification + Routing

- **Classification**: Decide the **intent** of the user message (same four types for now, extensible later).
- **Routing**: Map that intent (and optional hints) to a **single chosen path** (route) and optional **tool** (e.g. “rag”, “listing”, “direct”, future “write_file”). The orchestrator then **dispatches** to the right handler without hard‑coded if/else for every route.
- **Extensibility**: New routes (e.g. “save summary to file”) = new route id + handler; classification can later return a “suggested route” or “tool” so we can add tools without rewriting the core flow.

So we are not (yet) building a full multi-step agent loop—we are introducing a **single-step router** that runs once per turn and chooses the path. That keeps latency similar to today while making the design agent-ready.

---

## 3. Code Structure (Proposed)

### 3.1 New module: `ai/services/routing/`

Put all classification + routing logic in one place so the orchestrator stays a coordinator and doesn’t own classification details.

```
ai/services/
  routing/
    __init__.py
    router.py          # Router class: classify + resolve route
    classifier.py      # Classification logic (fast path, cache, LLM)
    routes.py          # Route definitions (enum or constants + metadata)
    schemas.py         # RouteResult, optional ToolHint (for future)
  document_processor/
    orchestrator.py    # Uses router; dispatches by route
    ...
```

**Responsibilities:**

- **`routes.py`**: Define route ids and metadata (e.g. `Route.GREETING`, `Route.DOCUMENT_LISTING`, `Route.DOCUMENT_SEARCH`, `Route.GENERAL`). Optional: which retrieval config key, whether it needs RAG, etc.
- **`classifier.py`**: Contains (or wraps) current classification logic: fast path, cache key, LLM prompt, validation. Input: `(question, conversation_history)`. Output: **label** (e.g. `greeting`, `general`, `document_listing`, `document_search`). No dependency on orchestrator.
- **`router.py`**: Uses classifier; maps **label → route**. Returns a **RouteResult**: `route: Route`, `query_type: str` (for existing metrics/config), optional `tool_hint` for future. Can be extended later to accept tool-calling output (e.g. “use RAG + write_file”).
- **`schemas.py`**: Pydantic/dataclass for `RouteResult` (and optional `ToolHint`) so the rest of the app doesn’t depend on routing internals.

### 3.2 How the orchestrator changes

- **Orchestrator** receives `(question, conversation_history)` and optionally precomputed `query_embedding`.
- **Step 1**: Call `router.resolve(question, conversation_history)` → get `RouteResult`.
- **Step 2**: **Dispatch** by `route`:
  - `Route.GREETING` or `Route.GENERAL` → `_generate_direct_response(question, response_type)` (no retrieval).
  - `Route.DOCUMENT_LISTING` → `_get_document_listing()`.
  - `Route.DOCUMENT_SEARCH` → `_retrieve_chunks(...)` + build context + `generate_response` / `generate_response_stream`.
- **Step 3**: Same as today: build `QueryResult` or stream events; include `query_type` from `RouteResult` for metrics and `query_config`.

So the orchestrator no longer calls `_classify_query` directly; it calls the router and branches on `route`. All classification and route definitions live under `routing/`.

### 3.3 Dependencies and boundaries

- **Router** depends on: LLM (for classification when not fast path/cache). So the router needs an LLM abstraction (e.g. “generate_simple” for one-off classification). Options:
  - Pass `LLMService` (or a thin interface) into the router, or
  - Keep the router pure (label → route) and let the **orchestrator** own the LLM call for classification; then the “classifier” is just fast path + cache + prompt builder, and the orchestrator calls `llm_service.generate_simple(prompt)` and passes the result into the router.
- **Recommendation**: Router takes a **classifier** that has `async classify(question, conversation_history) -> str`. The classifier is implemented in `classifier.py` and can hold cache + fast path and call an injected LLM. That way routing stays testable and the orchestrator only depends on `Router.resolve()`.

### 3.4 Config and metrics

- **query_config.py**: No change to `RetrievalConfig`. It already keys on `query_type` (greeting, general, document_listing, document_search). The router will continue to set `query_type` on `RouteResult` so retrieval config and metrics stay as they are.
- **Metrics / main.py**: Still use `query_type` from the stream (or from `QueryResult`). No change needed unless we later add a separate “route” dimension.

---

## 4. Data Flow (After Refactor)

```
User message + conversation_history
        │
        ▼
┌───────────────────┐
│  Router.resolve   │  ← classifier (fast path → cache → LLM) → label → route
└─────────┬─────────┘
          │ RouteResult(route, query_type)
          ▼
┌───────────────────┐
│  Orchestrator     │
│  dispatch by route│
└─────────┬─────────┘
          │
    ┌─────┴─────┬─────────────────┬──────────────────┐
    ▼           ▼                 ▼                  ▼
 GREETING   GENERAL    DOCUMENT_LISTING    DOCUMENT_SEARCH
    │           │                 │                  │
    ▼           ▼                 ▼                  ▼
 _generate_direct_response   _get_document_listing   _retrieve_chunks
                                                      + generate_response(_stream)
```

Classification + embedding can still run in parallel at the orchestrator: start `router.resolve()` and `embedding_service.encode_single_text()` together; await both; then dispatch. So latency stays comparable.

---

## 5. What Goes Where (Summary)

| What | Where (after) |
|------|----------------|
| Route enum/constants | `routing/routes.py` |
| Fast path + cache + LLM classification | `routing/classifier.py` |
| Label → route mapping, RouteResult | `routing/router.py` |
| RouteResult (and optional ToolHint) | `routing/schemas.py` |
| Dispatch by route, retrieval, generation | `orchestrator.py` (calls router, no classification logic) |
| Query type for config/metrics | Still `query_type` on result; set from RouteResult |

---

## 6. How to Start (Phased)

### Phase 1 — Extract classification into a service (no behavior change)

1. Add `ai/services/routing/` with `__init__.py`, `routes.py`, `schemas.py`, `classifier.py`, `router.py`.
2. **routes.py**: Define `Route` (enum or string constants): `GREETING`, `GENERAL`, `DOCUMENT_LISTING`, `DOCUMENT_SEARCH`. Optionally a map `query_type -> Route` for backward compatibility.
3. **schemas.py**: Define `RouteResult(route: Route, query_type: str)`.
4. **classifier.py**: Move from orchestrator:
   - `_classify_query_fast_path`
   - `_classification_cache_key`
   - `_classify_query` (rename to e.g. `async classify(question, conversation_history, llm)` or take an injected “llm_caller”).
   - Classification cache lives inside the classifier (or in the router that holds the classifier). Cache key and max size stay the same.
5. **router.py**: `Router` class that holds a `Classifier` (and optionally LLM reference). `resolve(question, conversation_history) -> RouteResult`: call classifier, then map label → route and query_type (same string as today).
6. **Orchestrator**:
   - Instantiate `Router` (and pass LLM or classifier that uses orchestrator’s LLM).
   - In `query()` and `query_stream()`: replace `_classify_query` with `router.resolve()`; replace `if query_type in ['greeting','general']` with `if route in (Route.GREETING, Route.GENERAL)`, etc. Keep all retrieval and generation logic; only the source of “route”/“query_type” changes.
7. Run existing tests (orchestrator query tests, classification tests). Fix any breakage so behavior is identical.

### Phase 2 — Make routing extensible (optional, right after or later)

- Add a small **registry** of route handlers in the orchestrator (e.g. dict `route -> async handler(question, context)`) so adding a new route is “add enum + handler” instead of a new if-branch.
- Optionally add `ToolHint` to `RouteResult` and document how future tools (e.g. “write_file”) would be selected (e.g. classifier or a second LLM call returning “tools”: ["write_file"]).

### Phase 3 — Future agents

- Multi-step agent or tool use: the same router can later return “route: RAG, tools: [write_file]”; the orchestrator runs RAG first, then runs the tool in the same turn or in the background.

---

## 7. File-by-File Checklist (Phase 1)

| File | Action |
|------|--------|
| `ai/services/routing/__init__.py` | Export `Router`, `Route`, `RouteResult`, `Classifier` (or whatever is public). |
| `ai/services/routing/routes.py` | Define `Route` and mapping from classification label to route + query_type. |
| `ai/services/routing/schemas.py` | Define `RouteResult`. |
| `ai/services/routing/classifier.py` | Move classification (fast path, cache, LLM prompt), no orchestrator imports. |
| `ai/services/routing/router.py` | Implement `Router.resolve()` using classifier and routes. |
| `ai/services/document_processor/orchestrator.py` | Create router (inject LLM or classifier), call `router.resolve()` in `query`/`query_stream`, dispatch by `route`; remove `_classify_query*` and classification cache. |
| `ai/main.py` | No change (still uses `query_type` from stream). |
| `ai/schemas/chat.py` | No change (unless we add a formal “route” in API response later). |
| `ai/services/document_processor/query_config.py` | No change. |
| Tests | Update any tests that call `_classify_query` to use the router or the new classifier; ensure classification and query tests still pass. |

---

## 8. Risk and Rollback

- **Risk**: Moving code can introduce subtle bugs (e.g. cache key difference, wrong default). Mitigation: keep behavior identical in Phase 1; run full query and classification tests; optionally keep old `_classify_query` behind a feature flag and compare outputs for a few days.
- **Rollback**: Revert the orchestrator to call `_classify_query` and keep the new `routing/` module unused, or remove the routing module and restore classification into the orchestrator from git history.

---

## 9. Success Criteria (Phase 1)

- All existing classification and query flows behave the same (greeting, general, document_listing, document_search).
- Classification and routing live under `ai/services/routing/`; orchestrator only dispatches by route.
- Existing tests pass (orchestrator, classification, streaming).
- No new latency: classification + embedding still run in parallel where they do today.

Once this is in place, adding a new route (e.g. “save summary”) is: add a route id, add a handler in the orchestrator (or to a handler registry), and optionally extend the classifier to return that label when appropriate.
