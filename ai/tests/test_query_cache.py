"""
Tests for query result cache (bounded LRU + TTL).
Run from ai/: python -m pytest tests/test_query_cache.py -v
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from query_cache import QueryCache, get_query_cache_key, DEFAULT_TTL_SECONDS, DEFAULT_MAX_ENTRIES


def test_cache_key_deterministic():
    """Same inputs produce same key."""
    k1 = get_query_cache_key("tenant1", 1, "hello")
    k2 = get_query_cache_key("tenant1", 1, "hello")
    assert k1 == k2


def test_cache_key_tenant_isolated():
    """Different tenants get different keys for same session/message."""
    k1 = get_query_cache_key("alice", 1, "hi")
    k2 = get_query_cache_key("bob", 1, "hi")
    assert k1 != k2


def test_cache_key_session_isolated():
    """Different sessions get different keys."""
    k1 = get_query_cache_key("t", 1, "hi")
    k2 = get_query_cache_key("t", 2, "hi")
    assert k1 != k2


def test_cache_key_normalizes_message():
    """Leading/trailing whitespace normalized in key."""
    k1 = get_query_cache_key("t", 1, "  hello  ")
    k2 = get_query_cache_key("t", 1, "hello")
    assert k1 == k2


def test_cache_miss_returns_none():
    """Unknown key returns None."""
    c = QueryCache(max_entries=10, ttl_seconds=60)
    assert c.get("nonexistent") is None


def test_cache_set_and_get():
    """Set then get returns value."""
    c = QueryCache(max_entries=10, ttl_seconds=60)
    key = get_query_cache_key("t", 1, "q")
    val = {"message": "answer", "sources": []}
    c.set(key, val)
    assert c.get(key) == val


def test_cache_ttl_expiry():
    """Expired entry returns None."""
    c = QueryCache(max_entries=10, ttl_seconds=0)  # expire immediately
    key = get_query_cache_key("t", 1, "q")
    c.set(key, {"message": "x", "sources": []})
    assert c.get(key) is None


def test_cache_ttl_not_expired():
    """Non-expired entry is returned."""
    c = QueryCache(max_entries=10, ttl_seconds=10)
    key = get_query_cache_key("t", 1, "q")
    c.set(key, {"message": "x", "sources": []})
    assert c.get(key) == {"message": "x", "sources": []}


def test_cache_bounded_eviction():
    """When at capacity, oldest (LRU) is evicted."""
    c = QueryCache(max_entries=2, ttl_seconds=60)
    k1 = get_query_cache_key("t", 1, "q1")
    k2 = get_query_cache_key("t", 2, "q2")
    k3 = get_query_cache_key("t", 3, "q3")
    c.set(k1, {"message": "a1", "sources": []})
    c.set(k2, {"message": "a2", "sources": []})
    assert c.get(k1) is not None
    c.set(k3, {"message": "a3", "sources": []})
    assert len(c) == 2
    # k1 was oldest (or k2); one of them evicted. k2 and k3 should be present (k1 evicted first if LRU)
    assert c.get(k3) is not None
    # After 2 inserts, k1 get moved to end when we did get(k1). So order was k2, k1. Then set k3 evicts k2.
    assert c.get(k2) is None
    assert c.get(k1) is not None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
