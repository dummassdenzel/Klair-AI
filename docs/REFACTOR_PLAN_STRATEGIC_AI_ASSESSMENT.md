# Honest Assessment of Third-Party Critique (REFACTOR_PLAN_STRATEGIC_AI.md)

This document records which parts of the third-party review we **accept**, **partially accept**, or **push back on**, and how the strategic plan is updated as a result.

---

## Verdict on the critique

The review is **substantively correct** and raises no wrong-headed ideas. The 8.5/10 is fair: the plan’s direction is right, but several design choices were suboptimal. Below is where we agree, where we refine, and where we don’t change.

---

## 1. What the plan gets right — **Agree**

No disagreement. The critique’s summary (root problem = intent before LLM; phased migration; keep retrieval; tool contract; entity tracking in Phase C) matches our intent. No edits needed to the plan for this section.

---

## 2. Single-loop tool calling vs planner + answer (two LLM calls) — **Accept**

**Their point:** Two calls (planner → tools → answer) add latency and cost. Prefer one LLM conversation where the model emits tool calls, system runs tools, returns results, model continues to final answer.

**Our take:** Correct. Modern tool-calling (OpenAI functions, Groq/Llama tool use) is one conversation loop, not separate “planner” and “answer” models. Our plan described two steps because it was written in a provider-agnostic way; we should **prefer single-loop tool calling** when the model supports it and treat the two-step (planner + answer) as a **fallback** for models without tool use.

**Plan change:** In Phase B, state that the **preferred** design is one LLM with a tool-calling loop; the “planner then answer” flow is the fallback. Add a short note on Groq/Llama tool support.

---

## 3. Query rewriting before retrieval — move to Phase B — **Accept**

**Their point:** If the user says “when was that delivered?” the planner might output `search_documents("when was that delivered")` and retrieval fails. Rewriting must happen **before** retrieval, and should be in Phase B.

**Our take:** Correct. We had put “query rewriting” in Phase C with entity tracking, but **retrieval quality in Phase B** already depends on resolved references. So we need **minimal** entity context in Phase B: e.g. “last cited document” per session, and a rewrite step that substitutes “that”/“it”/“this document” with that entity **before** the planner’s tool choice (or before tool execution). Full entity tracking (multiple entities, concepts, etc.) can stay in Phase C.

**Plan change:** Phase B includes “query rewriting with minimal entity context (e.g. last cited document)” so that any `search_documents(...)` call receives a resolved query. Phase C then adds full entity tracking and richer rewriting.

---

## 4. Corpus summary = richer metadata — **Accept**

**Their point:** Don’t only store a prose “folder summary.” Store corpus **statistics**: document_count, categories, category_counts, date_range, common keywords. That enables much richer answers.

**Our take:** Correct. A single text blob is fragile and hard to query. Stored **structured metadata** (counts, categories, date range) can drive both a generated summary and direct answers (“how many invoices?”, “date range?”). We can still generate a short prose summary from this for summarize_corpus.

**Plan change:** In Phase A, specify that we store **corpus metadata** (document_count, categories/counts, date_range, optional keywords) and that summarize_corpus (or the listing path) uses this. Prose summary can be derived from this metadata.

---

## 5. Planner hallucination / guardrails — **Accept (emphasize more)**

**Their point:** Planner could output the wrong tool (e.g. search when user asked “what files do we have”). Need strict JSON schema validation, fallback behavior, and prompt constraints.

**Our take:** We already had “fallback: invalid planner output → search_documents(user_message)” in Risks. The critique is right that **guardrails** deserve an explicit subsection: schema validation for tool choice/args, fallback rules, and prompt constraints (e.g. “if the user asks what files/documents exist, use list_documents”).

**Plan change:** Add a “Planner guardrails” subsection under Phase B: strict schema for tool name and arguments, fallback when invalid, and prompt constraints to reduce tool misuse.

---

## 6. search_specific_document(name) tool — **Accept**

**Their point:** Add a tool that restricts retrieval to one document by name. We have FilenameTrie; use it. “Explain BIP-12046” should search only that file.

**Our take:** Correct. We already do single-file intent and filename detection in the current codebase. Exposing this as `search_specific_document(name)` (or `search_documents(query, document_name?)`) makes intent explicit and avoids over-retrieval. Fits the existing stack.

**Plan change:** Add `search_specific_document(name: str)` to the Phase B tool contract, implemented via FilenameTrie + retrieval restricted to that document.

---

## 7. Phase ordering — **Accept (already implied by #3)**

**Their point:** Do query rewriting in Phase B, not only in Phase C.

**Our take:** Covered by accepting point 3. Phase B now includes “query rewriting with minimal entity context.” Phase C remains “full entity tracking + richer rewriting.” No separate reorder of phases; the change is *what* we put in B.

---

## 8. Avoiding LangChain/ReAct/unbounded loops — **Acknowledge**

**Their point:** The plan wisely avoids LangChain agents, ReAct, and unbounded tool loops; the structured planner is safer.

**Our take:** We intentionally kept the design simple and deterministic (fixed tool set, no open-ended ReAct). We can add one sentence in the plan acknowledging that we are **not** adopting unbounded agent loops or heavy agent frameworks.

---

## 9. Latency estimate — **No change**

**Their point:** Planner adds ~400–800 ms; total still within 1–7 s.

**Our take:** Already in our risks. If we move to single-loop tool calling, we may save one round-trip. No plan change beyond the Phase B preference for single-loop.

---

## 10. Where we slightly push back (or clarify)

- **“Planner/answer split may be unnecessary”:** We now **agree** and have made single-loop the preferred option. The “split” is only a fallback.
- **“Query rewriting should happen earlier”:** Agreed; moved into Phase B with minimal entity context.
- **“Corpus summary could be richer”:** Agreed; we specify structured corpus metadata in Phase A.
- **“Tool guardrails need emphasis”:** Agreed; we add an explicit subsection.

We do **not** push back on any of the critique’s main recommendations.

---

## Summary: plan updates

| Item | Action |
|------|--------|
| Single-loop tool calling | Phase B: prefer one LLM with tool-calling loop; two-step as fallback. |
| Query rewriting | Phase B: add “query rewriting with minimal entity context” before retrieval/tool execution. |
| Corpus summary | Phase A: store corpus metadata (counts, categories, date_range); use for summary and listing. |
| Planner guardrails | Phase B: add “Planner guardrails” (schema, fallback, prompt constraints). |
| search_specific_document | Phase B: add to tool contract; implement via FilenameTrie + filtered retrieval. |
| Unbounded agents | One-sentence note: we do not adopt LangChain/ReAct/unbounded tool loops. |

The strategic plan document (REFACTOR_PLAN_STRATEGIC_AI.md) is updated to reflect these decisions.
