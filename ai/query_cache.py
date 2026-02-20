"""
Bounded, TTL in-memory cache for chat query results.
Reduces repeated LLM/retrieval cost for identical questions in the same session.
"""
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600  # 1 hour
DEFAULT_MAX_ENTRIES = 500


class QueryCache:
    """
    In-memory LRU cache for RAG query results with TTL.
    Bounded size; evicts oldest when full.
    Entries expire after ttl_seconds; expired entries are dropped on access.
    """

    __slots__ = ("_store", "_order", "max_entries", "ttl_seconds")

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, Dict[str, Any]] = {}
        self._order: OrderedDict[str, None] = OrderedDict()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() - entry["ts"] >= self.ttl_seconds:
            self._store.pop(key, None)
            self._order.pop(key, None)
            return None
        self._order.move_to_end(key)
        return entry["value"]

    def set(self, key: str, value: Dict[str, Any]) -> None:
        while len(self._store) >= self.max_entries and self._order:
            evict_key = next(iter(self._order))
            self._store.pop(evict_key, None)
            self._order.pop(evict_key, None)
        self._store[key] = {"value": value, "ts": time.time()}
        self._order[key] = None
        self._order.move_to_end(key)

    def __len__(self) -> int:
        return len(self._store)


def get_query_cache_key(session_id: int, message: str) -> str:
    """Build cache key from session + normalized message."""
    normalized = (message or "").strip()
    payload = f"{session_id}:{normalized}"
    return hashlib.sha256(payload.encode()).hexdigest()
