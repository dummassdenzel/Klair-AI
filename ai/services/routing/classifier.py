"""
Query classifier: pure heuristic, zero LLM calls.
Returns one of: greeting, general, document_listing, document_search.

Role in the pipeline
--------------------
1. Pre-filter in _run_shared_pipeline(): called before the planner on every query
   for Ollama/Gemini providers.  GREETING, GENERAL, and DOCUMENT_LISTING routes
   are short-circuited here without any LLM call.  Only DOCUMENT_SEARCH proceeds
   to the planner.
2. Fallback in _pipeline_legacy(): used as the full routing path when the planner
   raises an exception.

Expanding the regex/word lists is fine; they are the authoritative signal for
non-search intents and carry no LLM latency cost.
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

# Casual/small-talk phrases that should get a short friendly response, not RAG
_CASUAL_PHRASES = frozenset({
    "whats up", "what's up", "whats new", "what's new",
    "how are you", "how are ya", "how's it going", "hows it going",
    "how is it going", "how are things", "whats going on", "what's going on",
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

# If a query also asks for values/totals, it needs search_documents — route to agent instead.
_VALUE_SEEKING_RE = re.compile(
    r"\b(?:total(?: value| amount| cost| price)?|sum|how much|grand total|amount due|"
    r"overall (?:value|amount|cost)|add(?:ed)? up|tally|breakdown of (?:costs?|amounts?|values?))\b",
    re.IGNORECASE,
)

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
        # "how many files/documents do we have" (generic count)
        r"^(?:how many|total(?: number of)?) (?:files?|documents?) (?:do )?(?:we|i) have",
        # "how many [document category] do we have / are there" (category count)
        # Matches: "how many delivery receipts do we have", "how many invoices are there", etc.
        r"how many [\w\s]+ (?:do (?:we|i) have|are (?:there|in (?:our|my|the) (?:folder|files?|index))|exist)",
        # "count [category]" / "total number of [category]"
        r"^(?:count|total(?: number of)?|give me (?:a )?count of) [\w\s]+$",
        # "what are our delivery receipts", "what are the invoices", "what are all the permits"
        # Intent: enumerate documents by category — must route to list_documents, not search.
        r"^what (?:are|were) (?:all )?(?:our|the|my)(?: the)? [\w ]+$",
        # "what delivery receipts do we have", "what invoices do we have"
        r"^what [\w ]+ do (?:we|i) have\s*$",
        # "show me all [our/the] delivery receipts", "give me all the invoices"
        r"^(?:show|give)(?: me)?(?: all)? (?:our|the|my|all(?: (?:our|the|my))?) [\w ]+$",
    ]
]


def _normalize(text: str) -> str:
    """Lowercase query with trailing punctuation stripped so listing regexes match."""
    s = text.strip().rstrip("?!.,").strip().lower()
    return s


def _is_greeting(q: str) -> bool:
    if q in _CASUAL_PHRASES:
        return True
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
    if _VALUE_SEEKING_RE.search(q):
        return False
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
