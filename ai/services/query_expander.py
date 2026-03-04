"""
Query expansion for retrieval: rewrites the user query into richer search variants
before hybrid retrieval. Improves recall when document wording differs from user wording
(e.g. "when did the shipment arrive?" vs "Delivery date", "Arrival date" in docs).

Fits after pronoun rewrite (B.1) and before search_documents / search_specific_document.
Only used for search tools, not for greetings or listing.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from services.document_processor.llm.llm_service import LLMService

logger = logging.getLogger(__name__)

# Strip common LLM list prefixes (e.g. "1.", "2.", "- ") before using as query variant
LINE_PREFIX_PATTERN = re.compile(r"^[\s]*(\d+[.)]\s*|-\s*)*", re.IGNORECASE)

# Max tokens for the expansion LLM call (keep it cheap)
EXPANSION_MAX_TOKENS = 150

EXPANSION_PROMPT = """You are a query expansion helper for a document search system. The user's search query is given below. Output 1 to 3 alternative search queries (one per line) that rephrase or expand the query with synonyms and related terms to improve retrieval. Focus on terms that might appear in business, shipping, or legal documents (e.g. delivery, shipment, arrival, receipt, invoice, permit, date, value, quantity). Keep each query concise (under 15 words). If the query is already specific and rich, you may output just one line. Output only the queries, one per line, no numbering or labels.

Query: {query}

Expanded queries (one per line):"""


async def expand_query_for_retrieval(
    query: str,
    llm_service: "LLMService",
    max_variants: int = 3,
) -> List[str]:
    """
    Expand a search query into 1–3 variants for better retrieval recall.
    Uses a small LLM call. Returns the original query if expansion fails or returns empty.
    """
    if not query or not str(query).strip():
        return []
    query = str(query).strip()
    try:
        from services.document_processor.llm.provider_adapters import PROMPT_TYPE_CLASSIFICATION

        prompt = EXPANSION_PROMPT.format(query=query)
        response = await llm_service.generate_simple(
            prompt,
            prompt_type=PROMPT_TYPE_CLASSIFICATION,
            max_completion_tokens=EXPANSION_MAX_TOKENS,
        )
        if not response or not response.strip():
            logger.debug("Query expansion returned empty; using original query")
            return [query]
        lines = [line.strip() for line in response.strip().splitlines() if line.strip()]
        # Strip numbering/bullet prefixes (1. 2. - ) so we don't store "1. delivery receipt"
        stripped = [LINE_PREFIX_PATTERN.sub("", line).strip() for line in lines if line]
        stripped = [s for s in stripped if s]
        # Always include original query first; then add expansions (deduped), cap at max_variants
        seen = {query.lower()}
        variants: List[str] = [query]
        for line in stripped:
            if line.lower() not in seen and len(variants) < max_variants:
                seen.add(line.lower())
                variants.append(line)
        logger.info("Query expansion: '%s' -> %s", query, variants)
        return variants
    except Exception as e:
        logger.warning("Query expansion failed: %s; using original query", e)
        return [query]
