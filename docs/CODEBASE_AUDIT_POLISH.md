# Codebase Audit: Oversights, Optimizations, Future-Proofing

**Date:** 2025-02  
**Scope:** Post–Phase 5 polish; similar to BIP-12046-style identifier resolution and general robustness.

---

## 1. Fixes applied in this pass

### 1.1 LLM prompt: conversation summary role (bug)

- **Where:** `ai/services/document_processor/llm/llm_service.py` → `_build_prompt`
- **Issue:** Conversation history is rendered as `User` / `Assistant` only. The 5.3 **summary** is inserted as a message with `role="system"`, but the code treated it as `else` → **"Assistant"**, so the model saw: `Assistant: Summary of earlier conversation: ...`
- **Fix:** Handle `role == "system"` explicitly and render it as a separate context block (e.g. "Background:" or "Summary of earlier conversation:") so it is not confused with the assistant’s own prior replies. **Applied in code.**

---

## 2. Similar oversights / identifier resolution

### 2.1 Explicit filename: multiple matches

- **Where:** `_select_relevant_files` returns **all** trie matches for a stem (e.g. `"report"` → `report.pdf`, `report.docx`). `_retrieve_chunks` then filters by `explicit_filename in file_path`, so multiple files can still be in context.
- **Risk:** Low. User saying "explain report" getting both report.pdf and report.docx is acceptable. If you later want "single file only" when the query sounds singular, you could add heuristics (e.g. prefer one file when the stem matches exactly one filename with extension).
- **Action:** No change now; document for future.

### 2.2 Explicit filename: typo / no trie match

- **Where:** If the user says "explain BIP-12047" but the file is `BIP-12046.pdf`, the trie returns no match; `selected_files` is None and we rely on semantic retrieval.
- **Risk:** Same as before the BIP-12046 fix: retrieval may not dominate, so single-file mode might not trigger. No new bug.
- **Action:** Optional later: fuzzy stem match (e.g. one-edit distance) or "did you mean BIP-12046?" in the reply. Not implemented here.

### 2.3 Aggregation / listing regexes

- **Where:** `query_config.py` → `is_aggregation_query`; `classifier.py` → `_LISTING_PATTERNS`
- **Issue:** All are English and pattern-based. Queries like "total of all invoices" / "list all my documents" are covered; slight rephrasing could miss.
- **Action:** No code change. Add new patterns as you see real user queries that should be listing/aggregation.

---

## 3. Configuration and consistency

### 3.1 Supported extensions: two sources of truth

- **Where:** `config.py` → `Settings.SUPPORTED_EXTENSIONS` (env: `SUPPORTED_EXTENSIONS`) vs `file_validator.py` → `BASE_SUPPORTED_EXTENSIONS` (hardcoded).
- **Issue:** Orchestrator and file monitor use the validator (and thus the hardcoded set). Changing `SUPPORTED_EXTENSIONS` in `.env` does **not** change which files are indexed or monitored.
- **Action:** Either (a) have `FileValidator` accept an optional extension list from config and use it when provided, or (b) document that supported types are fixed in code and env is for display only. Recommended: (a) for future-proofing.

### 3.2 Magic numbers

- **Where:** `build_conversation_history`: `max_recent_pairs = 6`, `max_input_chars = 4000`; single-file thresholds: `0.6`, `0.8`, `primary_count >= 3`; classifier greeting: `len(tokens) > 4`.
- **Action:** These are fine as constants. If you need tuning, move to `query_config` or `config.py` later.

---

## 4. Robustness and edge cases

### 4.1 Conversation history: empty or malformed messages

- **Where:** `build_conversation_history` and router `_build_conversation_history`
- **Current:** We `.strip()` and skip empty user/assistant; we use `pair.get("user")` / `pair.get("assistant")`. If the DB has a message with both empty, we effectively drop that turn.
- **Risk:** Low. Consecutive "Assistant" lines could happen if some user messages were empty; some models might tolerate it.
- **Action:** No change. Optional: normalize consecutive same-role messages later.

### 4.2 Single-file mode: Chroma `get_document_chunks` return shape

- **Where:** `vector_store.get_document_chunks(file_path)`; orchestrator uses `all_chunks_data.get("documents")` and `all_chunks_data.get("metadatas")`.
- **Current:** Chroma `get()` returns a dict with `documents`, `metadatas`, `ids`. We handle `None` and missing keys.
- **Action:** None. If you switch embedding backend, keep this return shape or adapt the orchestrator in one place.

### 4.3 Retrieval: empty document list

- **Where:** `_retrieve_chunks` can return empty lists; `_retrieve_and_build_context` returns `None` and the API returns "I don't have information...".
- **Action:** None. Behavior is correct.

---

## 5. Optimizations (optional, not required now)

- **RAG context cap:** `rag_max_per_doc_chars: int = 0` (no cap). For very large single-file context, you could set a cap (e.g. 12k chars) to avoid blowing the LLM context window.
- **Summarization prompt:** One extra LLM call when history length > 6. If you need to reduce cost, you could raise the threshold (e.g. summarize only when > 10 pairs) or cap `max_input_chars` more aggressively.
- **Trie search:** Prefix-only. For "BIP 12046" (space) we would not detect it; the stem pattern requires a single token. Acceptable unless you see real user queries with spaces in IDs.

---

## 6. Future-proofing

- **Document identifier patterns:** `_find_explicit_filename` now allows stems with digits/hyphen/underscore. If you add new doc ID styles (e.g. "INV-2024-001"), the same pattern should still match; if you need new delimiters, extend the condition.
- **Extensions in config:** Making `FileValidator` (and thus indexing/monitoring) respect `Settings.SUPPORTED_EXTENSIONS` when set would allow enabling new file types without code change.
- **Logging:** No PII in logs; file paths can be long. If you ship logs, consider truncating paths or redacting.

---

## Summary

| Item | Severity | Status |
|------|----------|--------|
| LLM prompt: system role for summary | Bug | **Fixed** |
| Supported extensions vs config | Inconsistency | Documented; optional fix |
| Multiple files for one stem | Edge case | Documented; no change |
| Typo in filename | Edge case | Optional fuzzy later |
| Magic numbers / caps | Low | OK as-is |
| Empty/malformed conversation turns | Low | OK as-is |
