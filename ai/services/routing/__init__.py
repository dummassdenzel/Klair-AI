"""
Agentic classification + routing: classify query and resolve to a single route for dispatch.
"""

from .routes import Route, label_to_route, VALID_LABELS, LABEL_TO_ROUTE
from .schemas import RouteResult
from .classifier import QueryClassifier
from .router import Router

__all__ = [
    "Route",
    "RouteResult",
    "QueryClassifier",
    "Router",
    "label_to_route",
    "VALID_LABELS",
    "LABEL_TO_ROUTE",
]
