"""
Query classifier: pure heuristic, zero LLM calls.
Returns one of: greeting, general, document_listing, document_search.
"""

import logging
import re
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

_GREETING_WORDS = frozenset({
    "hi", "hello", "hey", "howdy", "hiya", "sup",
    "thanks", "thank", "thx", "ty",
    "bye", "goodbye", "cya", "later",
    "ok", "okay", "cool", "nice", "great",
    "good morning", "good afternoon", "good evening", "good night",
    "you", "yo", "there", "morning", "afternoon", "evening",
})

_GENERAL_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^what can you do",
        r"^what do you do",
        r"^how do(?:es)? (?:this|you) work",
        r"^what are you",
        r"^who are you",
        r"^help$",
        r"^what (?:are )?your (?:capabilities|features|functions)",
        r"^how (?:can|do) (?:i|we) use (?:this|you)",
        r"^what (?:is|are) (?:this|you) (?:for|about)",
        r"^tell me about yourself",
    ]
]

_LISTING_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^(?:list|show|display|give me|get)(?: me)? (?:all|every|the) (?:documents?|files?|indexed)\s*$",
        r"^what (?:documents?|files?) (?:do )?(?:we|i|you) have\s*$",
        r"^what(?:'s| is| are) indexed",
        r"^show (?:me )?(?:all|everything|the files?|the documents?)\s*$",
        r"^list (?:all|everything|documents?|files?)\s*$",
        r"^what(?:'s| is) (?:in )?(?:the|my|our) (?:directory|folder|workspace|index)",
        r"^overview of (?:(?:all|our|my|the) )?(?:files?|documents?)",
        r"^describe (?:(?:all|our|my|the) )?(?:files?|documents?)\s*$",
        r"^(?:how many|total(?: number of)?) (?:files?|documents?) (?:do )?(?:we|i) have",
    ]
]


def _normalize(text: str) -> str:
    return text.strip().rstrip("?!.").strip().lower()


def _is_greeting(q: str) -> bool:
    tokens = q.split()
    if not tokens or len(tokens) > 4:
        return False
    if all(t in _GREETING_WORDS for t in tokens):
        return True
    if q in _GREETING_WORDS:
        return True
    return False


def _is_general(q: str) -> bool:
    return any(p.search(q) for p in _GENERAL_PATTERNS)


def _is_document_listing(q: str) -> bool:
    return any(p.search(q) for p in _LISTING_PATTERNS)


class QueryClassifier:
    """
    Classifies user query into one of: greeting, general, document_listing, document_search.
    Pure heuristic — no LLM calls, no cache needed.
    """

    def __init__(self, llm_caller: Any = None, **_kwargs: Any):
        pass

    async def classify(
        self,
        question: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        q = _normalize(question)
        if not q:
            return "greeting"

        if _is_greeting(q):
            logger.info("Query classified as: greeting (heuristic)")
            return "greeting"

        if _is_general(q):
            logger.info("Query classified as: general (heuristic)")
            return "general"

        if _is_document_listing(q):
            logger.info("Query classified as: document_listing (heuristic)")
            return "document_listing"

        logger.info("Query classified as: document_search (default)")
        return "document_search"

    def clear_cache(self) -> None:
        """No-op kept for interface compatibility."""
        pass
