"""
Phase B.2 – Tool layer for the document assistant.
Tools are the stable API between reasoning (planner/LLM) and infrastructure
(retrieval, listing, corpus summary). Good tool design avoids wrong usage,
poor retrieval, and hallucinations.
"""

from .contract import (
    TOOL_LIST_DOCUMENTS,
    TOOL_SEARCH_DOCUMENTS,
    TOOL_SEARCH_SPECIFIC_DOCUMENT,
    TOOL_SUMMARIZE_CORPUS,
    TOOL_CALL_ITEM_SCHEMA,
    TOOLS_SCHEMA,
    ListDocumentsResult,
    SearchDocumentsResult,
    SummarizeCorpusResult,
    get_tools_for_planner,
    get_openai_format_tools,
    validate_tool_call,
    validate_tool_calls,
)

__all__ = [
    "TOOL_LIST_DOCUMENTS",
    "TOOL_SEARCH_DOCUMENTS",
    "TOOL_SEARCH_SPECIFIC_DOCUMENT",
    "TOOL_SUMMARIZE_CORPUS",
    "TOOL_CALL_ITEM_SCHEMA",
    "TOOLS_SCHEMA",
    "ListDocumentsResult",
    "SearchDocumentsResult",
    "SummarizeCorpusResult",
    "get_tools_for_planner",
    "get_openai_format_tools",
    "validate_tool_call",
    "validate_tool_calls",
]
