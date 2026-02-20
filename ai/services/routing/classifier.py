"""
Query classifier: fast path, cache, and LLM-based classification.
Domain-agnostic; returns one of: greeting, general, document_listing, document_search.
"""

import logging
from collections import OrderedDict
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

CLASSIFICATION_CACHE_MAX_SIZE = 500
CLASSIFICATION_CACHE_KEY_MAX_LEN = 300


class QueryClassifier:
    """
    Classifies user query into one of: greeting, general, document_listing, document_search.
    Uses fast path (greeting-only), LRU cache, then LLM.
    """

    def __init__(
        self,
        llm_caller: Any,  # Object with async generate_simple(prompt: str) -> str
        cache_max_size: int = CLASSIFICATION_CACHE_MAX_SIZE,
        cache_key_max_len: int = CLASSIFICATION_CACHE_KEY_MAX_LEN,
    ):
        self._llm = llm_caller
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._cache_max = max(1, cache_max_size)
        self._cache_key_max_len = max(1, cache_key_max_len)

    @staticmethod
    def _fast_path(question: str) -> Optional[str]:
        """
        Domain-agnostic fast path: greetings only.
        "What kind/type of files?" → leave to LLM so it can return document_listing (full list, then summarize by type).
        """
        q = question.strip().lower()
        if not q:
            return None
        q_clean = q.rstrip("?!.").strip()
        tokens = [t for t in q_clean.split() if t]
        if len(tokens) > 3:
            return None
        greeting_words = {"hi", "hello", "hey", "thanks", "thank", "you", "bye", "goodbye", "ok", "okay"}
        if all(t in greeting_words for t in tokens) and len(tokens) >= 1:
            return "greeting"
        return None

    def _cache_key(self, question: str, conversation_history: Optional[List[Dict[str, Any]]] = None) -> str:
        """Normalized cache key for classification."""
        q = question.strip().lower()[: self._cache_key_max_len]
        if not conversation_history or len(conversation_history) == 0:
            return q
        last = conversation_history[-2:] if len(conversation_history) >= 2 else conversation_history
        ctx = "|".join(m.get("content", "")[:80] for m in last if isinstance(m, dict))
        return (q + "|" + ctx)[: self._cache_key_max_len]

    async def classify(
        self,
        question: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Classify query into ONE of: greeting, general, document_listing, document_search.
        Uses fast path, then cache, then LLM.
        """
        try:
            fast = self._fast_path(question)
            if fast is not None:
                logger.info(f"Query classified as: {fast} (fast path)")
                return fast

            history = conversation_history or []
            cache_key = self._cache_key(question, history)
            if cache_key in self._cache:
                classification = self._cache[cache_key]
                self._cache.move_to_end(cache_key)
                logger.info(f"Query classified as: {classification} (cache)")
                return classification

            conversation_context = ""
            if history:
                conversation_context = "\n\nRecent conversation:\n"
                for msg in history[-2:]:
                    role = "User" if msg.get("role") == "user" else "Assistant"
                    conversation_context += f"{role}: {msg.get('content', '')[:150]}...\n"

            classification_prompt = f"""Classify this query into ONE category:

{conversation_context}
USER QUERY: "{question}"

CATEGORIES:
1. greeting - Greetings, pleasantries ("hello", "hi", "thanks", "goodbye")
2. general - Questions about the AI itself, not documents ("what can you do?", "how does this work?")
3. document_listing - Requests to list/show ALL documents with NO filter ("what files do we have?", "list all documents", "show me everything", "what's indexed?", "tell me about our files", "what are our documents", "describe our files", "overview of our files")
4. document_search - Questions that need retrieval or a FILTERED list by type/name/content, or questions about document content ("list all X", "give me X", "what's in X?", "who attended?", any request for a subset of documents or content)

IMPORTANT:
- If the user asks what KIND or TYPE of files/documents (e.g. "what kind of files do we have?", "what type of documents?") → document_search (so the assistant can summarize by file type/category, not dump the full list).
- If the user asks for a SUBSET of documents (by type, name, or category) → document_search.
- If the user asks to list/show ALL documents OR for an overview/summary of all files with no filter → document_listing.
- If query contains pronouns (that, it, this) or references previous context → document_search.
- Work for any domain: documents can be permits, invoices, contracts, schoolwork, office work, etc. Apply the same rules.

Respond with ONLY ONE WORD: greeting, general, document_listing, or document_search"""

            response = await self._llm.generate_simple(classification_prompt)
            classification = response.strip().lower()

            valid_types = ["greeting", "general", "document_listing", "document_search"]
            if classification not in valid_types:
                logger.warning(f"Invalid classification '{classification}', defaulting to document_search")
                classification = "document_search"

            while len(self._cache) >= self._cache_max:
                self._cache.popitem(last=False)
            self._cache[cache_key] = classification
            self._cache.move_to_end(cache_key)

            logger.info(f"Query classified as: {classification}")
            return classification

        except Exception as e:
            logger.error(f"Classification failed: {e}, defaulting to document_search")
            return "document_search"

    def clear_cache(self) -> None:
        """Clear classification cache (e.g. when clearing all data)."""
        self._cache.clear()
