"""
Route definitions for agentic classification + routing.
Maps classification labels to routes used by the orchestrator for dispatch.
"""

from enum import Enum


class Route(str, Enum):
    """Route id for dispatch. Backward-compatible with query_type for config/metrics."""
    GREETING = "greeting"
    GENERAL = "general"
    DOCUMENT_LISTING = "document_listing"
    DOCUMENT_SEARCH = "document_search"


# Valid classification labels from the classifier (same as query_type strings)
VALID_LABELS = frozenset({"greeting", "general", "document_listing", "document_search"})

# Map classifier label -> Route (1:1 for now)
LABEL_TO_ROUTE = {
    "greeting": Route.GREETING,
    "general": Route.GENERAL,
    "document_listing": Route.DOCUMENT_LISTING,
    "document_search": Route.DOCUMENT_SEARCH,
}


def label_to_route(label: str) -> Route:
    """Map classification label to Route. Defaults to DOCUMENT_SEARCH for unknown labels."""
    return LABEL_TO_ROUTE.get(label.strip().lower(), Route.DOCUMENT_SEARCH)
