# B.7 Test Questions — Validate Tool-Based Flow Before Deprecating Classifier

Use these questions to confirm the **tool/planner flow** is stable and correct before deprecating the regex classifier for routing (B.7). For each question, note:

- **Expected tools:** Which tool(s) should be requested (or none).
- **Expected behavior:** Brief description of a good response.
- **Pass/fail:** Whether the model chose the right tools and the answer was appropriate.

---

## 1. No tools (greeting / general)

The model should **not** call any tool; it should answer from general knowledge.

| # | Question | Expected tools | Expected behavior |
|---|----------|----------------|-------------------|
| 1.1 | Hello | None | Short greeting; no document list or search. |
| 1.2 | Hi there | None | Same as above. |
| 1.3 | What's up? | None | Casual reply; no RAG. |
| 1.4 | How are you? | None | Friendly reply; no documents. |
| 1.5 | What can you do? | None | Explains capabilities; no tool calls. |
| 1.6 | Who are you? | None | Short intro; no tool calls. |

**Pass criteria:** No `list_documents`, `search_documents`, `search_specific_document`, or `summarize_corpus`; response is conversational and not forced into document citations.

---

## 2. Listing (list_documents and/or summarize_corpus)

The model should call **list_documents** and/or **summarize_corpus**. It must **not** call `search_documents` for these.

| # | Question | Expected tools | Expected behavior |
|---|----------|----------------|-------------------|
| 2.1 | What files do we have? | list_documents, optionally summarize_corpus | List/overview of indexed documents; counts or types; no search. |
| 2.2 | What kind of files do we have? | list_documents, summarize_corpus | Overview by type (e.g. PDF, Excel); counts; date range. |
| 2.3 | Explain our files. | list_documents, summarize_corpus | Summary of what’s in the folder (types, counts, maybe themes). |
| 2.4 | Give me an overview of the folder. | list_documents, summarize_corpus | Same as above. |
| 2.5 | What documents are in this workspace? | list_documents, optionally summarize_corpus | List/overview of documents. |
| 2.6 | List all documents. | list_documents | Explicit list; may also get summary. |

**Pass criteria:** No `search_documents` or `search_specific_document`. Response uses folder overview / document list; citations like `[Folder Overview]` or `[Document List]` (not `[Document: list_documents]`).

---

## 3. General search (search_documents)

The model should call **search_documents(query)** with a sensible query (after any query rewriting).

| # | Question | Expected tools | Expected behavior |
|---|----------|----------------|-------------------|
| 3.1 | Do we have anything about delivery dates? | search_documents("delivery dates" or similar) | Answer based on retrieved chunks; citations to real documents. |
| 3.2 | Find documents mentioning invoices. | search_documents("invoices" or similar) | List or summary of invoice-related content; document citations. |
| 3.3 | When was the shipment received? | search_documents(...) (may need query expansion) | Answer from docs (e.g. dates); citations. |
| 3.4 | What do we have on HMR Philippines? | search_documents("HMR Philippines" or similar) | Content about HMR Philippines; citations. |

**Pass criteria:** `search_documents` is used with a reasonable query; answer is grounded in retrieved chunks; sources shown are real file names.

---

## 4. Specific document (search_specific_document)

The model should call **search_specific_document(document_name)**. No query expansion for this tool.

| # | Question | Expected tools | Expected behavior |
|---|----------|----------------|-------------------|
| 4.1 | Explain BIP-12046. | search_specific_document("BIP-12046" or "BIP-12046.pdf") | Explanation of that document only; citation to that file. |
| 4.2 | What is BIP-12046? | Same as above. | Same. |
| 4.3 | What's in BIP-12046.pdf? | search_specific_document("BIP-12046.pdf" or "BIP-12046") | Content summary of that file; citation to that file. |
| 4.4 | Summarize invoice.pdf. | search_specific_document("invoice.pdf" or "invoice") | Summary of that document (if present in folder). |

**Pass criteria:** Only `search_specific_document` (no generic `search_documents` unless multi-doc intent is clear). Answer scoped to the named document; correct filename in citations.

---

## 5. Query rewriting (follow-ups with “that” / “it”)

After a question about a specific document, a follow-up with “that” or “it” should be **rewritten** (B.1) so the tool receives a resolved query (e.g. document name + question), not the raw pronoun.

| # | Sequence | Expected behavior |
|---|----------|-------------------|
| 5.1 | User: Explain BIP-12046. → AI answers. → User: When was that delivered? | Rewritten to something like “when was BIP-12046 delivered?”; `search_specific_document("BIP-12046")` or `search_documents("when was BIP-12046 delivered")` with resolved query. Answer uses BIP-12046 content. |
| 5.2 | User: What's in BIP-12046.pdf? → AI answers. → User: Who signed it? | “It” resolved to BIP-12046; search restricted or query resolved to that doc; answer about signatory. |
| 5.3 | User: Tell me about invoice.pdf. → AI answers. → User: What's the total amount on that? | “That” resolved to invoice.pdf; answer about that invoice’s total. |

**Pass criteria:** Follow-up answer is about the **previously discussed document**, not a generic or wrong doc. Logs or behavior show rewritten query (no raw “when was that delivered?” sent to retrieval).

---

## 6. Multiple tools in one turn

The model may call **two tools** when the question clearly asks for both listing and summary.

| # | Question | Expected tools | Expected behavior |
|---|----------|----------------|-------------------|
| 6.1 | What files do we have and what are they about? | list_documents and summarize_corpus | Both list and high-level summary; no search. |
| 6.2 | List our documents and summarize the folder. | list_documents, summarize_corpus | Same. |

**Pass criteria:** Both tools invoked; single coherent answer using list + summary; no inappropriate `search_documents`.

---

## 7. Guardrail / planner sanity (especially for two-step flow)

These check that the **planner** (or tool-calling model) does not choose search when the user clearly asks for a list/overview. Important for B.5 guardrails and safe default.

| # | Question | Must NOT use | Must use (or equivalent) |
|---|----------|--------------|---------------------------|
| 7.1 | What files do we have? | search_documents, search_specific_document | list_documents and/or summarize_corpus |
| 7.2 | Explain our files. | search_documents | list_documents, summarize_corpus |
| 7.3 | What kind of files are in the folder? | search_documents | list_documents, summarize_corpus |

**Pass criteria:** No search tool for 7.1–7.3. If the planner (Ollama/Gemini) ever returns search for these, the B.5 safe default should correct it to listing/summary tools.

---

## 8. Edge cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| 8.1 | Empty or whitespace message | Treated as greeting or rejected gracefully; no tools or safe default. |
| 8.2 | Document name that doesn’t exist (e.g. “Explain Nonexistent.pdf”) | search_specific_document may run; answer should state no/limited info, not hallucinate content. |
| 8.3 | Very long question (e.g. paste of a paragraph) | Still results in one of: no tools, list/summary, or search with a reasonable derived query; no crash. |

---

## Quick checklist for B.7 readiness

- [ ] **1.x** All greeting/general questions get no tool calls and natural replies.
- [ ] **2.x** All listing questions use only list_documents/summarize_corpus; no search.
- [ ] **3.x** General search questions use search_documents and return grounded answers.
- [ ] **4.x** Specific-document questions use search_specific_document and cite the right file.
- [ ] **5.x** Follow-ups with “that”/“it” are rewritten and answered in the context of the prior document.
- [ ] **6.x** Multi-tool questions trigger both list and summary tools when appropriate.
- [ ] **7.x** Listing-style questions never trigger search (or safe default fixes planner mistakes).
- [ ] **8.x** Edge cases handled without crashes and with sensible behavior.

When all sections pass consistently (on both Groq tool-calling and, if used, Ollama/Gemini planner path), the tool-based flow is **stable and tested** and you can proceed with **B.7 Deprecate classifier for routing**.
