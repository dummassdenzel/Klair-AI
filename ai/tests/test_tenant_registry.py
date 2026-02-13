"""
Tests for tenant registry and per-tenant persist dir.
Run from ai/: python -m pytest tests/test_tenant_registry.py -v
Or: cd ai && python tests/test_tenant_registry.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from tenant_registry import (
    TenantRegistry,
    TenantContext,
    get_tenant_persist_dir,
    get_tenant_id_from_request,
    DEFAULT_TENANT_ID,
    TENANT_HEADER,
    MAX_TENANTS,
)


def test_get_tenant_persist_dir_default():
    """Default tenant keeps same path (backward compat)."""
    assert get_tenant_persist_dir("/data", DEFAULT_TENANT_ID) == "/data"
    assert get_tenant_persist_dir("/var/chroma", "default") == "/var/chroma"


def test_get_tenant_persist_dir_isolated():
    """Non-default tenants get stable isolated subdir."""
    p1 = get_tenant_persist_dir("/data", "user1")
    p2 = get_tenant_persist_dir("/data", "user2")
    assert p1 != p2
    assert p1.startswith("/data/t_")
    assert p2.startswith("/data/t_")
    assert len(p1) == len("/data/t_") + 12  # 12-char hash suffix
    # Same tenant_id -> same path
    assert get_tenant_persist_dir("/data", "user1") == p1


def test_registry_empty():
    """New registry has no tenants."""
    r = TenantRegistry(max_tenants=5)
    assert len(r) == 0
    assert r.get("any") is None


def test_registry_set_and_get():
    """Set and get tenant context."""
    r = TenantRegistry(max_tenants=5)
    ctx = TenantContext(
        tenant_id="alice",
        doc_processor=None,
        file_monitor=None,
        current_directory="/path/a",
    )
    r.set("alice", ctx)
    assert len(r) == 1
    got = r.get("alice")
    assert got is ctx
    assert got.current_directory == "/path/a"


def test_registry_get_unknown_returns_none():
    """Unknown tenant returns None."""
    r = TenantRegistry(max_tenants=5)
    r.set("alice", TenantContext("alice", None, None, "/a"))
    assert r.get("bob") is None


def test_registry_evict():
    """Evict removes tenant."""
    r = TenantRegistry(max_tenants=5)
    r.set("alice", TenantContext("alice", None, None, "/a"))
    assert len(r) == 1
    r.evict("alice")
    assert len(r) == 0
    assert r.get("alice") is None


@pytest.mark.asyncio
async def test_registry_evict_one_lru():
    """evict_one_lru removes oldest (first in order)."""
    r = TenantRegistry(max_tenants=2)
    r.set("a", TenantContext("a", None, None, "/a"))
    r.set("b", TenantContext("b", None, None, "/b"))
    assert len(r) == 2
    # "a" is LRU (oldest). Evict one.
    evicted = await r.evict_one_lru()
    assert evicted == "a"
    assert len(r) == 1
    assert r.get("a") is None
    assert r.get("b") is not None


@pytest.mark.asyncio
async def test_registry_evict_and_cleanup():
    """evict_and_cleanup evicts and runs cleanup (no crash if monitor/processor None)."""
    r = TenantRegistry(max_tenants=5)
    r.set("alice", TenantContext("alice", None, None, "/a"))
    await r.evict_and_cleanup("alice")
    assert r.get("alice") is None


def test_registry_bounded_lru_eviction():
    """When at capacity, set() evicts LRU to make room."""
    r = TenantRegistry(max_tenants=2)
    r.set("a", TenantContext("a", None, None, "/a"))
    r.set("b", TenantContext("b", None, None, "/b"))
    # Add third; "a" should be evicted (oldest)
    r.set("c", TenantContext("c", None, None, "/c"))
    assert len(r) == 2
    assert r.get("a") is None
    assert r.get("b") is not None
    assert r.get("c") is not None


def test_get_tenant_id_from_request_no_header():
    """Missing header returns default tenant."""
    class Req:
        headers = {}
    assert get_tenant_id_from_request(Req()) == DEFAULT_TENANT_ID


def test_get_tenant_id_from_request_with_header():
    """X-Tenant-ID is used when present."""
    class Req:
        headers = {TENANT_HEADER: "  my-tenant-1  "}
    assert get_tenant_id_from_request(Req()) == "my-tenant-1"


def test_tenant_ids():
    """tenant_ids returns list of registered ids."""
    r = TenantRegistry(max_tenants=5)
    assert r.tenant_ids() == []
    r.set("a", TenantContext("a", None, None, "/a"))
    r.set("b", TenantContext("b", None, None, "/b"))
    ids = r.tenant_ids()
    assert set(ids) == {"a", "b"}
    assert len(ids) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
