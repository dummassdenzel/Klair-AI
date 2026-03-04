"""
Context compression for retrieval (Phase T.3).
Extracts only question-relevant portions from each chunk; preserves original wording.
No summarization or paraphrasing. Reduces context tokens before the answer model.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from services.document_processor.llm.llm_service import LLMService

logger = logging.getLogger(__name__)

# Skip compression when total context is small (avoids unnecessary LLM calls)
SKIP_COMPRESSION_TOTAL_CHARS = 2000
SKIP_COMPRESSION_MIN_CHUNKS = 2

# Safeguards: fallback to original if compression removes too much; cap output size
MIN_COMPRESSED_CHARS = 30
MAX_COMPRESSED_CHARS = 400

# Truncate chunk when sending to compressor to avoid token explosion
MAX_CHUNK_INPUT_CHARS = 4000

# Output token limit per chunk (small model, extraction only)
COMPRESSION_MAX_OUTPUT_TOKENS = 200

COMPRESSION_PROMPT = """You are compressing document text for a retrieval system.

Given the question and document text, extract only the parts that are useful for answering the question.

Rules:
- Keep original wording from the document. Do not summarize or paraphrase.
- Preserve important identifiers: headings, document labels, section names, filenames.
- Keep minimal surrounding context if needed for clarity.
- If nothing in the text is relevant, return an empty string.

Question:
{question}

{file_context}Document text:
{chunk}

Return only the relevant excerpts from the document."""


async def compress_chunks(
    question: str,
    chunks: List[str],
    llm_service: "LLMService",
    filenames: Optional[List[str]] = None,
) -> List[str]:
    """
    Compress each chunk by extracting only question-relevant portions.
    Preserves original wording. Returns list aligned with input order.
    When filenames is provided (one per chunk), prepends "File: {filename}" so the
    compressor and output retain document identity for citation and cross-document reasoning.
    Safeguards: fallback to original when compressed too short; cap compressed size.
    """
    if not chunks or not question or not str(question).strip():
        return list(chunks) if chunks else []

    total_chars = sum(len(c) for c in chunks)
    if total_chars < SKIP_COMPRESSION_TOTAL_CHARS or len(chunks) < SKIP_COMPRESSION_MIN_CHUNKS:
        logger.debug(
            "Context compression skipped: total_chars=%s, num_chunks=%s",
            total_chars,
            len(chunks),
        )
        return list(chunks)

    use_filenames = (
        filenames is not None
        and len(filenames) == len(chunks)
    )

    async def compress_one(i: int, chunk: str, filename: Optional[str] = None) -> str:
        chunk_trimmed = chunk.strip()
        if len(chunk_trimmed) > MAX_CHUNK_INPUT_CHARS:
            chunk_trimmed = chunk_trimmed[:MAX_CHUNK_INPUT_CHARS].rstrip() + "\n[...]"
        file_context = f"File: {filename}\n\n" if filename else ""
        prompt = COMPRESSION_PROMPT.format(
            question=question.strip(),
            file_context=file_context,
            chunk=chunk_trimmed,
        )
        try:
            out = await llm_service.generate_simple(
                prompt,
                prompt_type="classification",
                max_completion_tokens=COMPRESSION_MAX_OUTPUT_TOKENS,
            )
        except Exception as e:
            logger.warning("Compression failed for chunk %s: %s", i, e)
            return _fallback_chunk(chunk)
        out = (out or "").strip()
        if len(out) < MIN_COMPRESSED_CHARS:
            return _fallback_chunk(chunk)
        if len(out) > MAX_COMPRESSED_CHARS:
            out = out[:MAX_COMPRESSED_CHARS].rstrip() + "\n[...]"
        return out

    def _fallback_chunk(chunk: str) -> str:
        """Use original chunk (truncated) when compression removed too much."""
        c = chunk.strip()
        if len(c) > MAX_COMPRESSED_CHARS:
            c = c[:MAX_COMPRESSED_CHARS].rstrip() + "\n[...]"
        return c

    results = await asyncio.gather(
        *[
            compress_one(i, c, filenames[i] if use_filenames else None)
            for i, c in enumerate(chunks)
        ],
        return_exceptions=True,
    )
    out_list: List[str] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("Compression error for chunk %s: %s", i, r)
            out_list.append(_fallback_chunk(chunks[i]))
        else:
            out_list.append(r)

    logger.info(
        "Context compression: %s chunks, total chars %s -> %s",
        len(chunks),
        total_chars,
        sum(len(s) for s in out_list),
    )
    return out_list
