# Testing the LRU Metadata Cache (Unbounded Memory Fix)

This guide covers how to verify that the bounded metadata cache and DB-backed stats work correctly.

## 1. Unit tests for `MetadataCache`

From the **`ai`** directory:

```bash
cd ai
python tests/test_metadata_cache.py
```

This runs:

- **Bounded size**: Adding more than `max_size` entries evicts the oldest.
- **LRU behavior**: `get()` moves the entry to the end; next eviction removes the least recently used.
- **get/remove/clear**: Cache API behaves as expected.
- **Orchestrator**: Has `_metadata_cache`, `get_stats()` is async and returns `total_files`, `metadata_cache_size`, `indexed_files`.

To run the same tests with pytest (if installed):

```bash
cd ai
python -m pytest tests/test_metadata_cache.py -v
```

## 2. Existing orchestrator / document processor tests

These were updated to `await get_stats()` and should still pass:

```bash
cd ai
python tests/test_document_processor.py
```

Optional (if you have a test directory with documents and DB configured):

```bash
cd ai
python tests/test_ocr.py
python tests/test_phase3_integration.py
```

## 3. Quick smoke test with the running app

1. **Start the backend** (from `ai`):

   ```bash
   cd ai
   uvicorn main:app --reload
   ```

2. **Check status (includes index stats)**:

   ```bash
   curl -s http://127.0.0.1:8000/api/status | python -m json.tool
   ```

   In `index_stats` you should see:

   - `total_files` (from DB)
   - `metadata_cache_size` (≤ 2000)
   - `indexed_files` (list, capped at 500)

3. **Set a directory and index a few files** via the UI or:

   ```bash
   curl -X POST http://127.0.0.1:8000/api/set-directory -H "Content-Type: application/json" -d "{\"path\": \"C:\\path\\to\\your\\docs\"}"
   ```

4. **Call status again** and confirm:

   - `total_files` matches the number of indexed documents.
   - `metadata_cache_size` is at most 2000 and grows only up to that.

## 4. What to look for

| Check | Expected |
|-------|----------|
| No `file_hashes` / `file_metadata` on orchestrator | Code uses `_metadata_cache` only |
| `get_stats()` | Async; returns `total_files`, `metadata_cache_size`, `indexed_files` |
| Memory over time | With 1000+ files, metadata memory stays bounded (cache cap 2000) |
| Indexing and queries | Same behavior as before (DB + cache); no functional regressions |

## 5. If something fails

- **`AttributeError: 'DocumentProcessorOrchestrator' object has no attribute 'file_metadata'`**  
  Some test or script still uses the old API. Replace with `await orchestrator.get_stats()` and/or `orchestrator.filename_trie.file_count` / `orchestrator._metadata_cache` as needed (see `test_agentic_selection.py`).

- **`TypeError: object NoneType can't be used in 'await'`**  
  `get_stats()` must be awaited: use `await doc_processor.get_stats()`.

- **DB errors in tests**  
  Ensure the test DB (or your configured DB) is running and that `get_document_by_path` / `get_indexed_file_paths` are used only when the DB is available (or mock them in unit tests).
