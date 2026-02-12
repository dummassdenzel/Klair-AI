"""
Tests for the LRU MetadataCache and bounded-memory orchestrator behavior.
Run from ai/: python -m pytest tests/test_metadata_cache.py -v
Or: cd ai && python tests/test_metadata_cache.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor.orchestrator import MetadataCache, DEFAULT_METADATA_CACHE_MAX_SIZE


def test_metadata_cache_bounded_size():
    """Cache must not grow beyond max_size."""
    cache = MetadataCache(max_size=3)
    cache.set("/path/a", "hash_a", {"size": 1})
    cache.set("/path/b", "hash_b", {"size": 2})
    cache.set("/path/c", "hash_c", {"size": 3})
    assert len(cache) == 3

    # Add one more; oldest should be evicted
    cache.set("/path/d", "hash_d", {"size": 4})
    assert len(cache) == 3
    assert "/path/a" not in cache
    assert "/path/d" in cache


def test_metadata_cache_get_moves_to_end():
    """get() should move entry to end (LRU); eviction removes oldest (first)."""
    cache = MetadataCache(max_size=3)
    cache.set("a", "h1", {})
    cache.set("b", "h2", {})
    cache.set("c", "h3", {})

    # Access "a" so it moves to end; order is now b, c, a. Add "d" -> evict oldest = "b"
    cache.get("a")
    cache.set("d", "h4", {})
    assert "b" not in cache  # b was oldest (first) after a moved to end
    assert "a" in cache
    assert "c" in cache
    assert "d" in cache


def test_metadata_cache_get_returns_none_on_miss():
    """get() returns None for unknown path."""
    cache = MetadataCache(max_size=10)
    assert cache.get("/nonexistent") is None


def test_metadata_cache_remove_and_clear():
    """remove() and clear() work."""
    cache = MetadataCache(max_size=10)
    cache.set("a", "h1", {})
    cache.set("b", "h2", {})
    cache.remove("a")
    assert len(cache) == 1
    assert "a" not in cache
    cache.clear()
    assert len(cache) == 0


async def test_orchestrator_uses_cache_and_get_stats_async():
    """Orchestrator has _metadata_cache and get_stats is async and returns expected keys."""
    from services.document_processor import DocumentProcessorOrchestrator

    orch = DocumentProcessorOrchestrator(persist_dir="./test_chroma_metadata_cache")
    try:
        assert hasattr(orch, "_metadata_cache")
        assert isinstance(orch._metadata_cache, MetadataCache)
        assert orch._metadata_cache.max_size == DEFAULT_METADATA_CACHE_MAX_SIZE

        stats = await orch.get_stats()
        assert "total_files" in stats
        assert "metadata_cache_size" in stats
        assert "indexed_files" in stats
        assert isinstance(stats["indexed_files"], list)
        assert stats["metadata_cache_size"] <= DEFAULT_METADATA_CACHE_MAX_SIZE
    finally:
        if hasattr(orch, "update_worker") and orch.update_worker and getattr(orch.update_worker, "is_running", False):
            await orch.update_worker.stop()
        await orch.cleanup()
        if os.path.exists("./test_chroma_metadata_cache"):
            import shutil
            shutil.rmtree("./test_chroma_metadata_cache", ignore_errors=True)


def run_tests():
    """Run tests when executed as script."""
    print("Testing MetadataCache (LRU bounded)...")
    test_metadata_cache_bounded_size()
    print("  ok bounded_size")
    test_metadata_cache_get_moves_to_end()
    print("  ok get_moves_to_end")
    test_metadata_cache_get_returns_none_on_miss()
    print("  ok get_returns_none_on_miss")
    test_metadata_cache_remove_and_clear()
    print("  ok remove_and_clear")

    print("Testing orchestrator cache and get_stats...")
    asyncio.run(test_orchestrator_uses_cache_and_get_stats_async())
    print("  ok orchestrator_uses_cache_and_get_stats_async")

    print("\nAll metadata cache tests passed.")


if __name__ == "__main__":
    run_tests()
