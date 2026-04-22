"""
Phase B.1 – Query rewriting (Design A: pre-processing before LLM/retrieval).

Minimal goal: resolve follow-ups like:

  User:  explain BIP-12046
  User:  when was that delivered?

into a rewritten query:

  "when was BIP-12046.pdf delivered?"

So retrieval / tools receive a clean query that contains the explicit document
identifier, leveraging FilenameTrie and existing filename matching.

This module is deliberately conservative: it only rewrites short queries that
clearly refer to "that/this document/file" or "it".
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)


def _extract_last_document_name_from_sources(sources: Sequence[dict[str, Any]] | None) -> Optional[str]:
    """
    Given a list of RAG source dicts from the last chat message, return a display
    name to use in rewriting (e.g. "report.pdf"). Returns None if nothing usable.
    """
    if not sources:
        return None
    for src in sources:
        file_path = src.get("file_path")
        if not file_path or not isinstance(file_path, str):
            continue
        name = Path(file_path).name
        if name:
            return name
    return None


def rewrite_with_last_document(question: str, last_sources: Sequence[dict[str, Any]] | None) -> str:
    """
    Rewrite the user's question using the last referenced document, if applicable.

    - Only rewrites short queries (to avoid aggressive changes to long prompts).
    - Only triggers when we see pronouns like "that", "this", or "it" or phrases
      like "this document/file", "that document/file", "the document/file".
    - Replaces the first matching phrase with the last document's filename.

    If no rewrite is applicable, returns the original question.
    """
    if not isinstance(question, str):
        return question
    original = question
    q = question.strip()
    if not q:
        return original

    # Hard length cap: do not rewrite long, complex questions.
    if len(q) > 160:
        return original

    last_doc_name = _extract_last_document_name_from_sources(last_sources)
    if not last_doc_name:
        return original

    lower = q.lower()

    # If the filename is already present in the query, do not rewrite.
    if last_doc_name.lower() in lower:
        return original

    # Only consider rewriting if we see a relevant pronoun/phrase.
    if not re.search(r"\b(that|this|it)\b", lower) and "document" not in lower and "file" not in lower:
        return original

    # Token-based guard for "it": only allow rewriting "it" on short queries.
    tokens = q.split()
    allow_it_rewrite = len(tokens) <= 8

    # Ordered from most specific to most generic.
    patterns = [
        r"\bthis document\b",
        r"\bthat document\b",
        r"\bthis file\b",
        r"\bthat file\b",
        r"\bthe document\b",
        r"\bthe file\b",
        r"\bit\b",
        r"\bthat\b",
        r"\bthis\b",
    ]

    rewritten = original
    for pat in patterns:
        if pat == r"\bit\b" and not allow_it_rewrite:
            continue
        if re.search(pat, rewritten, flags=re.IGNORECASE):
            rewritten = re.sub(pat, last_doc_name, rewritten, count=1, flags=re.IGNORECASE)
            break

    if rewritten != original:
        logger.debug("Rewrote query: '%s' → '%s' (doc=%s)", original, rewritten, last_doc_name)
    return rewritten
