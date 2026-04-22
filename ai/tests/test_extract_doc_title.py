"""Tests for extract_doc_title — taxonomy-driven document type detection."""

import pytest
from unittest.mock import patch
from services.document_processor.extraction import text_extractor


def _with_types(*types):
    """Patch STANDALONE_DOC_TYPES for the duration of a test."""
    return patch.object(text_extractor, "STANDALONE_DOC_TYPES", frozenset(types))


def test_returns_none_when_taxonomy_is_empty():
    text = "INVOICE\nLine 2\nLine 3\n"
    assert text_extractor.extract_doc_title(text) is None


def test_returns_none_on_empty_text():
    assert text_extractor.extract_doc_title("") is None
    assert text_extractor.extract_doc_title(None) is None


def test_exact_match_returns_type():
    with _with_types("INVOICE", "CONTRACT"):
        text = "INVOICE\nSome body text\n"
        assert text_extractor.extract_doc_title(text) == "INVOICE"


def test_match_is_case_insensitive_and_whitespace_normalised():
    with _with_types("INVOICE"):
        assert text_extractor.extract_doc_title("invoice\nbody\n") == "INVOICE"
        assert text_extractor.extract_doc_title("INVOICE  \nbody\n") == "INVOICE"


def test_first_matching_line_wins():
    with _with_types("INVOICE", "CONTRACT"):
        text = "CONTRACT\nINVOICE\nbody\n"
        assert text_extractor.extract_doc_title(text) == "CONTRACT"


def test_no_match_returns_none():
    with _with_types("INVOICE"):
        text = "REPORT\nSome body text\n"
        assert text_extractor.extract_doc_title(text) is None


def test_partial_line_does_not_match():
    with _with_types("INVOICE"):
        text = "INVOICE COPY\nbody\n"
        assert text_extractor.extract_doc_title(text) is None
