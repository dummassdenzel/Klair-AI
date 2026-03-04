"""
Phase A: Corpus metadata and prose summary for document listing and future summarize_corpus tool.
Used to answer "what kind of files do we have?" and "explain our files" without retrieval.
"""

import logging
from typing import Dict, List, Any, Optional
from collections import Counter
from datetime import datetime

logger = logging.getLogger(__name__)


def _normalize_file_type(ft: Any) -> str:
    """Normalize file type for counting (pdf, PDF, Pdf -> pdf)."""
    if ft is None or (isinstance(ft, str) and not ft.strip()):
        return "unknown"
    s = str(ft).strip().lower()
    return s if s else "unknown"


def _safe_datetime(obj: Any) -> bool:
    """True if obj looks like a datetime we can use for min/max and strftime."""
    return obj is not None and hasattr(obj, "strftime") and callable(getattr(obj, "strftime", None))


def corpus_metadata_from_documents(docs: List[Any]) -> Dict[str, Any]:
    """
    Build corpus metadata from a list of document-like objects (e.g. IndexedDocument).
    Each doc must have: file_type, and optionally last_modified.
    File types are normalized to lowercase. Dates are guarded against None and invalid values.
    """
    if not docs:
        return {
            "document_count": 0,
            "file_type_counts": {},
            "date_range": None,
        }
    type_counts = Counter(_normalize_file_type(getattr(d, "file_type", None)) for d in docs)
    dates = [getattr(d, "last_modified", None) for d in docs if _safe_datetime(getattr(d, "last_modified", None))]
    date_range: Optional[tuple] = None
    if dates:
        try:
            date_range = (min(dates), max(dates))
        except (TypeError, ValueError):
            date_range = None
    return {
        "document_count": len(docs),
        "file_type_counts": dict(type_counts),
        "date_range": date_range,
    }


def build_corpus_summary(metadata: Dict[str, Any]) -> str:
    """
    Turn corpus metadata into a short prose summary (no LLM).
    Used to augment document_listing and for future summarize_corpus tool.
    """
    count = metadata.get("document_count", 0)
    if count == 0:
        return "No documents are currently indexed."
    type_counts = metadata.get("file_type_counts") or {}
    date_range = metadata.get("date_range")

    parts = [f"This folder contains {count} document(s)."]
    if type_counts:
        # Human-readable type labels (e.g. pdf -> PDF, docx -> Word)
        type_labels = {
            "pdf": "PDF",
            "docx": "Word",
            "doc": "Word",
            "xlsx": "Excel",
            "xls": "Excel",
            "pptx": "PowerPoint",
            "ppt": "PowerPoint",
            "txt": "Text",
            "md": "Markdown",
            "csv": "CSV",
        }
        by_type = []
        for ext, n in sorted(type_counts.items(), key=lambda x: -x[1]):  # sort by frequency descending
            label = type_labels.get(ext, ext.upper())  # ext already normalized to lower
            by_type.append(f"{label} ({n})")
        parts.append("By type: " + ", ".join(by_type) + ".")
    if date_range and len(date_range) == 2:
        low, high = date_range
        if _safe_datetime(low) and _safe_datetime(high):
            try:
                parts.append(f"Date range: {low.strftime('%b %Y')} – {high.strftime('%b %Y')}.")
            except (TypeError, ValueError):
                pass
    return " ".join(parts)


def summarize_corpus(docs: List[Any]) -> str:
    """
    Phase A capability for corpus overview. Used by document_listing and by the
    future Phase B summarize_corpus tool. Given a list of document-like objects,
    returns a short prose summary (no LLM).
    """
    metadata = corpus_metadata_from_documents(docs)
    summary = build_corpus_summary(metadata)
    # Debug log for "AI says we have N documents but we have M" troubleshooting
    date_str = "–"
    if metadata.get("date_range") and len(metadata["date_range"]) == 2:
        low, high = metadata["date_range"]
        if _safe_datetime(low) and _safe_datetime(high):
            try:
                date_str = f"{low.strftime('%b %Y')} – {high.strftime('%b %Y')}"
            except (TypeError, ValueError):
                pass
    logger.debug(
        "[CorpusSummary] documents=%s file_types=%s date_range=%s",
        metadata.get("document_count", 0),
        metadata.get("file_type_counts", {}),
        date_str,
    )
    return summary
