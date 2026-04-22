import logging
import re
from typing import List, Optional
from ..models import DocumentChunk

logger = logging.getLogger(__name__)

# Strips PDF layout markers added by the column-detection path in text_extractor.py.
# These markers help build previews but are noise inside embedded chunks.
_REGION_MARKER_RE = re.compile(r"\[Region: \w+\]\n?")

# Conservative char-to-token ratio for English text.
# Used as a fallback when no actual tokenizer is wired in.
_CHARS_PER_TOKEN = 4


class DocumentChunker:
    """
    Splits document text into overlapping chunks sized in **tokens**, not characters.

    chunk_size    — target chunk size in tokens (default 300)
    chunk_overlap — overlap between adjacent chunks in tokens (default 50)
    max_tokens    — hard cap matching the embedding model's context window (default 512)

    A HuggingFace tokenizer can be wired in after construction via set_tokenizer().
    Until then _count_tokens() falls back to len(text) // 4 (conservative estimate).
    """

    def __init__(
        self,
        chunk_size: int = 300,
        chunk_overlap: int = 50,
        max_tokens: int = 512,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_tokens = max_tokens
        self._tokenizer = None  # set via set_tokenizer() once the embedding model loads

    # ------------------------------------------------------------------
    # Tokenizer integration
    # ------------------------------------------------------------------

    def set_tokenizer(self, tokenizer) -> None:
        """
        Wire in the HuggingFace tokenizer from the embedding model for accurate
        token counts.  Call this once the embedding model has been loaded.
        """
        self._tokenizer = tokenizer
        logger.debug("Chunker: tokenizer wired in (%s)", type(tokenizer).__name__)

    def _count_tokens(self, text: str) -> int:
        """Return the number of tokens in *text*."""
        if self._tokenizer is not None:
            try:
                return len(self._tokenizer.encode(text, add_special_tokens=True))
            except Exception:
                pass
        return max(1, len(text) // _CHARS_PER_TOKEN)

    def _trim_to_max_tokens(self, text: str) -> str:
        """
        Trim *text* so it fits within self.max_tokens.
        Uses the real tokenizer when available; falls back to char approximation.
        The result is stripped of leading/trailing whitespace.
        """
        if self._tokenizer is not None:
            try:
                ids = self._tokenizer.encode(text, add_special_tokens=False)
                if len(ids) <= self.max_tokens - 2:
                    return text.strip()
                trimmed_ids = ids[: self.max_tokens - 2]  # reserve 2 for CLS/SEP
                return self._tokenizer.decode(trimmed_ids, skip_special_tokens=True).strip()
            except Exception:
                pass
        approx_chars = (self.max_tokens - 2) * _CHARS_PER_TOKEN
        return text[:approx_chars].rstrip()

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def create_chunks(self, text: str, file_path: str) -> List[DocumentChunk]:
        """Create overlapping token-sized chunks with semantic boundary detection."""
        text = _REGION_MARKER_RE.sub("", text)
        # Derive character-space window sizes from token targets.
        # Over-estimated slightly so _find_chunk_boundary has room to pull back.
        char_window = self.chunk_size * _CHARS_PER_TOKEN
        char_overlap = self.chunk_overlap * _CHARS_PER_TOKEN

        # Single-chunk fast path: whole text fits within one chunk.
        # Always apply the hard-cap trim even on this path — the fallback
        # char-based token estimate (len // 4) can undercount for dense
        # OCR text (numbers, codes, currency), so we cannot skip the check.
        if len(text) <= char_window:
            chunk_text = text
            if self._count_tokens(chunk_text) > self.max_tokens:
                chunk_text = self._trim_to_max_tokens(chunk_text)
            chunk_text = chunk_text.strip()
            if chunk_text:
                return [DocumentChunk(
                    text=chunk_text,
                    chunk_id=0,
                    total_chunks=1,
                    file_path=file_path,
                    start_pos=0,
                    end_pos=len(chunk_text),
                )]

        chunks: List[DocumentChunk] = []
        start = 0
        chunk_id = 0

        while start < len(text):
            end = min(start + char_window, len(text))

            # Pull end back to a semantic boundary when not at the document end
            if end < len(text):
                end = self._find_chunk_boundary(text, start, end)

            chunk_text = text[start:end].strip()

            # Hard-cap: ensure no chunk overflows the embedding model's context window
            if chunk_text and self._count_tokens(chunk_text) > self.max_tokens:
                chunk_text = self._trim_to_max_tokens(chunk_text)

            if chunk_text:
                chunks.append(DocumentChunk(
                    text=chunk_text,
                    chunk_id=chunk_id,
                    total_chunks=0,  # back-filled below
                    file_path=file_path,
                    start_pos=start,
                    end_pos=start + len(chunk_text),
                ))
                chunk_id += 1

            # Advance with overlap
            start = end - char_overlap
            if start >= len(text) - char_overlap:
                break

        for chunk in chunks:
            chunk.total_chunks = len(chunks)

        return chunks

    def _find_chunk_boundary(self, text: str, start: int, end: int) -> int:
        """
        Find the best split point at or before *end* within the window [start, end].

        Boundary priority (highest → lowest):
          1. Sentence ending (period, !, ?) — with false-positive guards
          2. Paragraph break (blank line)
          3. Any whitespace

        Lookback distances are proportional to the window span so the method
        works correctly regardless of the character window size passed in.

        False-positive guards for periods
        ----------------------------------
        A plain `.' followed by whitespace fires incorrectly on:
          - abbreviations : e.g., i.e., Mr., Dr., U.S.A.
          - decimal numbers: 3.14, 99.9 %   (these have *no* space after `.`,
                              so the existing whitespace check already skips them)
          - file paths / URLs: example.com/page  (no space after `.`)

        The remaining ambiguous case is abbreviations like "Mr. Smith" where
        a space *does* follow the period.  The fix: require that the first
        non-whitespace character after the `.` is uppercase.  A true new
        sentence always begins with an uppercase letter (or a digit/symbol for
        numbered items, which is handled by the paragraph-break tier anyway).
        `!` and `?` are unambiguous sentence terminators — no extra check needed.
        """
        span = end - start

        # ── tier 1: sentence endings ──────────────────────────────────────
        lookback = max(1, span // 10)
        for i in range(end - 1, max(end - lookback, start), -1):
            ch = text[i]
            if ch in "!?" and i + 1 < len(text) and text[i + 1].isspace():
                return i + 1
            if ch == ".":
                # Scan past any whitespace to find the first non-space char
                j = i + 1
                while j < len(text) and text[j] == " ":
                    j += 1
                # Split only if: end of text, or next real char is uppercase
                if j >= len(text) or text[j].isupper():
                    return i + 1

        # ── tier 2: paragraph break (blank line) ──────────────────────────
        lookback = max(1, span // 5)
        for i in range(end - 1, max(end - lookback, start), -1):
            if text[i] == "\n" and (i + 1 >= len(text) or text[i + 1] == "\n"):
                return i + 1

        # ── tier 3: any whitespace ────────────────────────────────────────
        lookback = max(1, span // 20)
        for i in range(end - 1, max(end - lookback, start), -1):
            if text[i].isspace():
                return i + 1

        return end
