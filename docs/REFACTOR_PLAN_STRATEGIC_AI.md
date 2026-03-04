# Strategic Refactor Plan: AI Assistant Architecture

> **Purpose:** This document is the **north star** for evolving the AI assistant from a **router-first, intent-brittle pipeline** into a **reasoning agent with tools** that can scale to ChatGPT-like conversation quality without regex explosion.
>
> **Reference:** Full system context and current strengths/weaknesses are in [LATEST_APPLICATION_AUDIT.md](./LATEST_APPLICATION_AUDIT.md). Tactical task lists remain in [REFACTOR_PLAN.md](./REFACTOR_PLAN.md).

---

## 1. The Core Problem

The current pipeline forces **intent to be decided before the LLM sees the query**:

```
User query
    ↓
Regex intent classifier (greeting | document_listing | document_search)
    ↓
Branch: run RAG or direct response
    ↓
RAG (if not greeting) → LLM
```

**Consequences:**

- **Intent brittleness:** "Explain our files", "what's in here", "give me a rundown" require new patterns. Users phrase the same intent in dozens of ways. We cannot enumerate them.
- **Intent rule explosion:** Each new failure mode is "fixed" by adding pattern 37, 38, 39. The classifier grows unbounded and remains incomplete.
- **RAG as default:** Anything that isn’t greeting/listable by regex goes to RAG. So "what's up?" triggers retrieval and produces "the documents do not contain the answer."
- **Wrong mental model:** We are building a **router**, not an **assistant**. The model never gets to decide what it needs.

Modern assistants (ChatGPT, Claude, Cursor) do not rely on rigid pre-classification for most queries. The **model** decides what to do; the system provides **tools** and **context**.

---

## 2. Target Architecture: Agent with Tools

The assistant should behave as a **reasoning agent with tools**, not a router.

**Target pipeline (preferred: single-loop tool calling):**

```
User query
    ↓
Conversation state (history + minimal entity context for rewriting)
    ↓
Query rewriting: resolve "that" / "it" / "this document" using last cited document
    ↓
LLM (one conversation with tool-calling support)
    → may request tools: list_documents | search_documents(query) | search_specific_document(name) | summarize_corpus
    ↓
System runs requested tools, returns results to LLM
    ↓
LLM continues in same conversation → final answer (streamed)
```

**Fallback (models without tool calling):** Two-step flow: planner LLM (returns which tool + args) → execute tools → answer LLM with results. Same tool contract; only the orchestration differs.

**Principles:**

- **Model decides.** The LLM sees the query and conversation, then chooses: no tools (e.g. "what's up?"), one tool (e.g. list_documents for "what files do we have?"), or multiple tools (e.g. search_specific_document then answer).
- **Retrieval only when needed.** RAG runs when the model explicitly requests document search or corpus summary, not by default.
- **Tools are first-class.** list_documents, search_documents, search_specific_document, summarize_corpus are stable APIs. New capabilities = new tools, not new regex branches.
- **Query rewriting before tools.** Resolve references ("that", "it") using minimal entity context **before** tool execution so search_documents receives a resolved query (e.g. "when was BIP-12046 delivered" not "when was that delivered").
- **Conversation is first-class.** Entity tracking (minimal in Phase B, full in Phase C) and query rewriting support "explain BIP-12046" → "when was that delivered" without the user repeating the document name.

**Note:** We do **not** adopt unbounded agent loops (e.g. LangChain-style ReAct with unlimited tool steps). The tool set is fixed and the loop is structured (one round of tool calls per turn, or one LLM conversation with tool use). This keeps behavior predictable and debuggable.

This aligns with Section 16 of [LATEST_APPLICATION_AUDIT.md](./LATEST_APPLICATION_AUDIT.md): *"Replace rule based routing with an LLM planning step"* and *"Planner LLM decides actions; system executes tools."*

---

## 3. What We Keep (No Regressions)

From the audit and current design, the following **must remain**:

| Component | Why |
|-----------|-----|
| **Hybrid retrieval** (Chroma + BM25 + RRF) | Strong recall; production-quality. |
| **FilenameTrie / explicit filename detection** | Critical for document-ID matching; keep as-is. |
| **Conversation history storage** | Required for follow-ups and future grounding. |
| **Streaming (SSE)** | UX and perceived latency. |
| **Cross-encoder reranking** | Relevance. |
| **Metadata filtering** | Queries like "total value of invoices". |

The **tools** we introduce will **call into** these components (e.g. `search_documents` uses the existing hybrid retrieval pipeline), not replace them.

---

## 4. What We Change

| Current | Target |
|--------|--------|
| Regex classifier chooses one path before LLM | LLM (planner) chooses which tools to call |
| RAG runs whenever query isn’t greeting/listing | RAG runs only when planner requests search_documents (or equivalent) |
| "No specific question" / over-grounding refusals | Assistant responds naturally; uses documents when relevant |
| No corpus-level understanding | summarize_corpus tool (and/or precomputed folder summary) |
| Follow-ups like "when was that delivered" rely on raw history | Entity tracking + query rewriting so "that" → last referenced document |

---

## 5. Phased Migration

We do **not** big-bang replace the router. We evolve in phases so each step is shippable and testable.

---

### Phase A — Foundation Without Changing the Router (Short-Term)

**Goal:** Improve behavior and data model so that the eventual agent has something to call. No removal of the classifier yet.

**A.1 Corpus summary and metadata**

- **Why:** "Explain our files" / "what kind of files" need **corpus-level** understanding, not chunk retrieval. The audit (Section 15) calls this out: *"During indexing, generate a folder summary."* A prose summary alone is limiting; structured metadata enables richer answers (counts, categories, date range).
- **What:**  
  - **Store corpus metadata** at index time (or when the index is stable): `document_count`, categories and `category_counts` (e.g. delivery notes, invoices), `date_range` if extractable, optional common keywords. This is the source of truth for "what's in this folder."  
  - **summarize_corpus** (or equivalent) can be: (i) a short prose summary generated from this metadata and stored/updated at index time, or (ii) a query-time call that takes the metadata (and optionally document list) and returns a narrative.  
  - When the **existing** classifier sends a query to **document_listing**, the listing response is augmented with this summary and/or metadata so "explain our files" gets a coherent overview (e.g. "This folder contains 312 documents: delivery notes (210), invoices (84), … Date range: Jan 2023 – Aug 2024").  
- **Deliverable:** Stored corpus metadata (counts, categories, date_range), a `summarize_corpus`-style capability that uses it, and wiring into the listing path.

**A.2 Softer RAG prompt**

- **Why:** "Answer using ONLY the document context" and "if the context doesn’t contain the answer, say so" make the model behave like a search engine and refuse valid overview requests.
- **What:** Rephrase to: use the documents when relevant; if the user asks for an overview or explanation of the documents, summarize what’s in the context; if the question is general conversation, respond normally; only say "the context doesn’t contain the answer" when the user clearly asked a factual question that isn’t in the context.
- **Deliverable:** Updated RAG system prompt in `llm_service.py` (or equivalent) and validation that refusals decrease for overview-style queries.

**A.3 Keep tactical classifier fixes only where they unblock UX**

- The recent additions (e.g. "explain our files" → listing, "what's up" → greeting) can stay as **temporary** patches. Document in code or in this plan that they are **interim** until the planner is in place. No further expansion of the regex list as a long-term strategy.

**Exit criteria:** Overview-style questions get a useful answer; small talk gets a short reply; RAG refusals are reduced. No architectural change to the router yet.

---

### Phase B — Introduce the Tool Layer and Reasoning (Core Shift)

**Goal:** The LLM decides which tools to use. We keep the existing retrieval and listing implementations; we only change **who** decides to call them. Prefer **single-loop tool calling** (one LLM conversation with tool use); support **two-step (planner + answer)** as fallback for models without tool-calling support.

**B.1 Query rewriting (before tools)**

- **Why:** If the user says "when was that delivered?" the model may request `search_documents("when was that delivered")` and retrieval will fail. The query passed to tools must be **resolved** using conversation context.
- **What:** Before the LLM runs (or before tool execution), apply **query rewriting** with **minimal entity context**: e.g. "last cited document" per session (from the previous assistant turn or user message). Substitute "that", "it", "this document" with the resolved document name so that e.g. "when was that delivered?" becomes "when was BIP-12046 delivered?" before `search_documents` is called.
- **Implementation:** Lightweight: store `last_cited_document` (or similar) per session; rule-based or small LLM rewrite. Full entity tracking (multiple entities, concepts) is Phase C.
- **Deliverable:** Rewritten user message (or resolved query) available when invoking tools. No tool receives a raw "when was that delivered" for retrieval.

**B.2 Define the tool contract**

- **Tools (minimal first set):**
  - `list_documents()` → returns list (and optionally metadata) of indexed documents for the current folder.
  - `search_documents(query: str)` → runs the existing hybrid retrieval + rerank pipeline, returns top chunks + sources. **Query must be rewritten** (see B.1) so it contains no unresolved "that"/"it".
  - `search_specific_document(name: str)` → restricts retrieval to the named document (e.g. "BIP-12046.pdf"). Uses FilenameTrie for resolution; runs same retrieval pipeline over that document only. Use for "Explain BIP-12046", "what's in that file?", etc.
  - `summarize_corpus()` → returns folder/corpus summary and metadata (from Phase A).
- **Stable API:** These are functions the backend can execute. The model’s job is to request one or more of these (or none).

**B.3 Preferred: single-loop tool calling**

- **When the model supports tool calling** (e.g. Groq + Llama): One LLM conversation. User message + history (+ rewritten query if needed) are sent; the model may emit tool calls (e.g. `search_specific_document("BIP-12046")`); backend runs tools, returns results to the same conversation; model continues and produces the final answer. Single round-trip for reasoning + answer; streaming on the final response.
- **Benefits:** Fewer LLM calls, lower latency, simpler pipeline, more flexible reasoning. This is the **preferred** design.

**B.4 Fallback: two-step (planner + answer)**

- **When the model does not support tool calling:** (1) **Planner** LLM: input = user message + history + entity context; output = structured choice (e.g. `action: "none"` | `list_documents` | `search_documents", query: "..."` | `search_specific_document", name: "..."` | `summarize_corpus`). (2) Backend runs the chosen tool(s). (3) **Answer** LLM: input = user message + history + tool results; output = streamed response.
- Same tool contract and query rewriting; only orchestration differs.

**B.5 Planner guardrails (two-step flow and tool-calling)**

- **Schema validation:** Tool name and arguments (query, name) must conform to a strict JSON schema. Reject malformed or unknown tools.
- **Fallback:** If the planner output is invalid or the model requests an inappropriate tool (e.g. search when the user clearly asked "what files do we have?"), fall back to a safe default (e.g. `list_documents` for listing-like intent, or `search_documents(rewritten_user_message)` for search-like intent). Do not blindly execute a mismatched tool.
- **Prompt constraints:** In the planner (or tool-calling) prompt, state clearly: e.g. "If the user asks what files or documents exist, or for an overview of the folder, use list_documents and/or summarize_corpus; do not use search_documents for that."

**B.6 Migration of existing paths**

- **Greeting / small talk:** Model requests no tools; responds directly. No regex needed.
- **"What files do we have?" / "Explain our files":** Model requests `list_documents` and/or `summarize_corpus`; we run them and pass results into the answer.
- **"What is BIP-12046?":** Model requests `search_specific_document("BIP-12046")` or `search_documents("BIP-12046")`; we run retrieval (with rewritten query if applicable) and pass context to the answer.

**B.7 Deprecate classifier for routing**

- Once the tool-based flow is stable and tested, **remove** the regex classifier from the **routing** path. The main path is: user → [rewrite] → LLM (with tools) → tools → answer. Classifier can remain for fallback or metrics only.

**Exit criteria:** All current successful behaviors (greeting, listing, search, overview) are achievable via model + tools; query rewriting ensures retrieval receives resolved queries; no regression in quality; retrieval runs only when the model requests it.

---

### Phase C — Conversational Grounding (Full Entity Tracking)

**Goal:** Extend beyond the minimal "last cited document" used in Phase B. Support richer follow-ups (e.g. "who signed it?", "compare that to the other invoice") and multiple entities. Phase B already introduced query rewriting with minimal entity context; Phase C adds **full** entity tracking and richer rewriting.

**C.1 Entity tracking**

- **What:** Maintain **conversation state**: last mentioned document(s), last mentioned concept (e.g. "delivery date"), and optionally a small set of recently referenced entities. Update from each user message and each assistant response (e.g. "BIP-12046.pdf" when we cite it or the user says it).
- **Where:** Server-side, per session; can be part of the same store as conversation history or a separate small structure.
- **Deliverable:** An entity store (e.g. "last_document_ids", "last_file_paths", "recent_entities") updated after each turn and passed into the next rewrite/planner step.

**C.2 Richer query rewriting**

- **What:** Use full entity state to rewrite references ("that", "it", "the other one", "the invoice") so that tool calls receive fully resolved queries. May use a small LLM for ambiguous cases (e.g. "compare that to the other one").
- **How:** Build on Phase B’s rewriting; extend with more entities and possibly an LLM rewrite step when rule-based substitution is insufficient.

**C.3 Model and answer use entity context**

- Model (tool-calling or planner) input includes current entity state so it can request the right tool with the right arguments. Answer can mention resolved documents where appropriate.

**Exit criteria:** Multi-turn conversation where the user refers to multiple documents or concepts ("that", "the other one", "the invoice") and the system correctly resolves and answers using the right documents.

---

### Phase D — Optional Enhancements (Later)

- **Multi-step tool use:** Planner may call multiple tools in one turn (e.g. list_documents then search_documents for one of them).
- **Richer tools:** e.g. `open_document(name)` (return full text or large chunks for that file), `aggregate_documents(query)` for numeric/table aggregation.
- **Structured document metadata:** Page, section, table (audit Section 15) for better citations; can be consumed by search and by the answer step.
- **Semantic chunking / code-aware chunking:** Per audit and existing refactor plan; improves retrieval quality and can be used by the same `search_documents` tool.

These are explicitly out of scope for the first three phases; they build on the agent + tools foundation.

---

## 6. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| **Planner adds latency** | Keep planner prompt small; single call, no retrieval. Consider caching for repeated or near-identical queries if needed. |
| **Planner / model misclassifies or misuses tools** | Strict JSON schema for tool name and arguments; fallback when invalid (e.g. default to `list_documents` for listing-like intent, `search_documents(rewritten_message)` for search). Prompt constraints: e.g. "use list_documents when the user asks what files exist." See Phase B guardrails. |
| **Token cost increase** | With **single-loop tool calling**, no extra call (one conversation with tool use). With **two-step** fallback, one extra planner call per turn. Prefer single-loop to avoid this. |
| **Breaking existing flows** | Phase B keeps the same retrieval and listing code; we only change the decision point. Roll out behind a flag or gradual rollout if needed. |

---

## 7. Success Criteria (Long-Term)

- **No intent rule explosion:** No need to add new regex patterns for new phrasings of "list files", "explain documents", "what's in here", etc.
- **Small talk and greetings:** Handled naturally by planner → "no tools" → answer, without special-case patterns.
- **Overview / corpus questions:** Answered via list_documents + summarize_corpus (or folder summary), not by forcing RAG to "find a chunk that explains our files."
- **Follow-up grounding:** "Explain BIP-12046" → "when was that delivered?" works with entity tracking and query rewriting.
- **RAG only when needed:** Retrieval runs when the model requests it, not by default for every non-greeting.

---

## 8. Relationship to Other Documents

- **[LATEST_APPLICATION_AUDIT.md](./LATEST_APPLICATION_AUDIT.md):** Source of truth for current architecture, strengths (keep), and weaknesses (address in this plan). Sections 13–16 and 18 directly inform this refactor.
- **[REFACTOR_PLAN.md](./REFACTOR_PLAN.md):** Tactical checklist (Phases 1–5). Phase 2’s heuristic classifier is accepted as a **temporary** solution until Phase B of this plan. New work items for "corpus summary", "planner", "entity tracking", "query rewriting" can be added there as sub-tasks under this strategic plan.
- **AI_RESPONSE_FIXES_PLAN.md:** Describes the tactical fixes already applied (listing patterns, casual phrases, RAG prompt). Consider that plan **superseded in strategy** by this document: we will not rely on expanding regexes long-term; we will move to planner + tools instead.
- **REFACTOR_PLAN_STRATEGIC_AI_ASSESSMENT.md:** Assessment of a third-party critique of this plan; records which recommendations were accepted and how this document was revised.

---

## 9. Next Steps (Recommended Order)

1. **Implement Phase A** (corpus metadata + summary, soft RAG prompt, document interim nature of classifier). Delivers immediate UX improvement and the data the agent will need.
2. **Design and implement Phase B** (query rewriting with minimal entity context, tool contract including `search_specific_document`, single-loop tool-calling preferred, two-step fallback, guardrails). This is the main architectural shift.
3. **Validate** Phase B on a set of representative queries (greeting, listing, overview, search, small talk, "explain BIP-12046", "when was that delivered?" with one prior turn). Compare to current behavior.
4. **Plan Phase C** (full entity tracking, richer query rewriting) and implement when Phase B is stable.

No code is prescribed in this document; it is the **plan**. Implementation details and task breakdowns belong in [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) or in dedicated design docs for each phase.

---

## 10. Revisions (Third-Party Review)

This plan was revised after a third-party architectural review. Key changes incorporated:

- **Single-loop tool calling** preferred over planner + answer (two LLM calls); two-step retained as fallback for models without tool use.
- **Query rewriting** moved into Phase B (before retrieval) with minimal entity context (e.g. last cited document); Phase C adds full entity tracking and richer rewriting.
- **Corpus summary** in Phase A extended to **structured corpus metadata** (document_count, categories, category_counts, date_range) in addition to or as the basis for a prose summary.
- **Planner guardrails** made explicit in Phase B: schema validation, fallback behavior, prompt constraints to reduce tool misuse.
- **search_specific_document(name)** added to the tool contract; leverages FilenameTrie and restricts retrieval to one document.
- **Explicit note** that we do not adopt unbounded agent loops (e.g. LangChain/ReAct); tool set and loop are structured.

A short assessment of the review is in [REFACTOR_PLAN_STRATEGIC_AI_ASSESSMENT.md](./REFACTOR_PLAN_STRATEGIC_AI_ASSESSMENT.md).
