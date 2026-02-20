"""
Schemas for the routing layer.
"""

from dataclasses import dataclass
from .routes import Route


@dataclass
class RouteResult:
    """Result of routing: which path to take and query_type for config/metrics."""
    route: Route
    query_type: str  # Same as today: greeting, general, document_listing, document_search
