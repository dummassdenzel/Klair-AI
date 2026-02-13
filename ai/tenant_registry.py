"""
Tenant-scoped state: one processor + monitor + directory per tenant.
Enables multi-tenancy without global state; bounded LRU eviction.
"""
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Header used to identify tenant (optional; default "default" for single-tenant)
TENANT_HEADER = "X-Tenant-ID"
DEFAULT_TENANT_ID = "default"
MAX_TENANTS = 10


def _tenant_persist_suffix(tenant_id: str) -> str:
    """Stable short suffix for persist_dir (safe for paths)."""
    return hashlib.sha256(tenant_id.encode()).hexdigest()[:12]


def get_tenant_persist_dir(base_persist_dir: str, tenant_id: str) -> str:
    """Per-tenant ChromaDB persist dir for isolation."""
    if tenant_id == DEFAULT_TENANT_ID:
        return base_persist_dir  # backward compat: default tenant uses same path as before
    return f"{base_persist_dir.rstrip('/')}/t_{_tenant_persist_suffix(tenant_id)}"


@dataclass
class TenantContext:
    """Per-tenant state."""
    tenant_id: str
    doc_processor: Any  # DocumentProcessorOrchestrator
    file_monitor: Any   # FileMonitorService
    current_directory: Optional[str]
    last_used_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_used_at = time.time()


class TenantRegistry:
    """
    Bounded registry of tenant_id -> TenantContext.
    LRU eviction when full; each tenant has isolated processor/monitor/directory.
    """
    __slots__ = ("_contexts", "max_tenants", "_order")

    def __init__(self, max_tenants: int = MAX_TENANTS):
        self.max_tenants = max_tenants
        self._contexts: Dict[str, TenantContext] = {}
        self._order: OrderedDict[str, None] = OrderedDict()  # tenant_id -> None, for LRU order

    def get(self, tenant_id: str) -> Optional[TenantContext]:
        ctx = self._contexts.get(tenant_id)
        if ctx is None:
            return None
        self._order.move_to_end(tenant_id)
        ctx.touch()
        return ctx

    def set(self, tenant_id: str, ctx: TenantContext) -> None:
        if tenant_id in self._contexts:
            self._order.move_to_end(tenant_id)
            self._contexts[tenant_id] = ctx
            return
        while len(self._contexts) >= self.max_tenants and self._order:
            evict_id = next(iter(self._order))
            self.evict(evict_id)
        self._contexts[tenant_id] = ctx
        self._order[tenant_id] = None

    def evict(self, tenant_id: str) -> None:
        """Remove and cleanup a tenant's context. Caller should stop monitor and cleanup processor."""
        ctx = self._contexts.pop(tenant_id, None)
        self._order.pop(tenant_id, None)
        if ctx:
            logger.info(f"Evicted tenant {tenant_id} from registry")

    async def evict_and_cleanup(self, tenant_id: str) -> None:
        """Evict tenant and stop monitor + cleanup processor."""
        ctx = self._contexts.get(tenant_id)
        if not ctx:
            return
        try:
            if ctx.file_monitor:
                await ctx.file_monitor.stop_monitoring()
            if ctx.doc_processor:
                await ctx.doc_processor.cleanup()
        except Exception as e:
            logger.warning(f"Cleanup for tenant {tenant_id}: {e}")
        self.evict(tenant_id)

    def ensure_capacity(self) -> None:
        """If at capacity, evict oldest (first in _order). Returns after one eviction or if not full."""
        while len(self._contexts) >= self.max_tenants and self._order:
            evict_id = next(iter(self._order))
            # Async cleanup will be done by caller (set_directory)
            break

    async def evict_one_lru(self) -> Optional[str]:
        """Evict the least recently used tenant. Returns evicted tenant_id or None."""
        if not self._order:
            return None
        evict_id = next(iter(self._order))
        await self.evict_and_cleanup(evict_id)
        return evict_id

    def tenant_ids(self) -> list:
        return list(self._order.keys())

    def __len__(self) -> int:
        return len(self._contexts)


def get_tenant_id_from_request(request: Any) -> str:
    """Read X-Tenant-ID header; default DEFAULT_TENANT_ID so single-tenant works without header."""
    if hasattr(request, "headers") and request.headers:
        tenant = request.headers.get(TENANT_HEADER)
        if tenant and tenant.strip():
            return tenant.strip()
    return DEFAULT_TENANT_ID
