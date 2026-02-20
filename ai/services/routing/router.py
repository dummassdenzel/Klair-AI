"""
Router: resolves (question, conversation_history) to a RouteResult.
Uses QueryClassifier then maps label -> route for orchestrator dispatch.
"""

import logging
from typing import Optional, List, Dict, Any

from .classifier import QueryClassifier
from .routes import Route, label_to_route
from .schemas import RouteResult

logger = logging.getLogger(__name__)


class Router:
    """Resolves user message to a single route for the orchestrator."""

    def __init__(self, classifier: QueryClassifier):
        self._classifier = classifier

    async def resolve(
        self,
        question: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> RouteResult:
        """
        Classify the query and return the route + query_type for dispatch and metrics.
        """
        label = await self._classifier.classify(question, conversation_history or [])
        route = label_to_route(label)
        return RouteResult(route=route, query_type=label)

    def clear_cache(self) -> None:
        """Clear classifier cache (e.g. when clearing all data)."""
        self._classifier.clear_cache()
