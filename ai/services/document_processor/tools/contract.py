"""
Phase B.2 – Tool contract: names, descriptions, parameter schemas, and return types.

This module is the single source of truth for the document assistant's tools.
- Use these names and schemas for planner output validation and LLM tool-calling.
- Return types are structured so the answer model always knows what it received.
- Clear "when to use" guidance reduces wrong tool usage and hallucinations.
"""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict

# ---------------------------------------------------------------------------
# Tool names (stable; do not change without migration)
# ---------------------------------------------------------------------------

TOOL_LIST_DOCUMENTS = "list_documents"
TOOL_SEARCH_DOCUMENTS = "search_documents"
TOOL_SEARCH_SPECIFIC_DOCUMENT = "search_specific_document"
TOOL_SUMMARIZE_CORPUS = "summarize_corpus"
TOOL_PROPOSE_DOCUMENT_EDIT = "propose_document_edit"
TOOL_RENAME_FILE = "rename_file"
TOOL_DELETE_FILE = "delete_file"
TOOL_MOVE_FILE = "move_file"

VALID_TOOL_NAMES = frozenset({
    TOOL_LIST_DOCUMENTS,
    TOOL_SEARCH_DOCUMENTS,
    TOOL_SEARCH_SPECIFIC_DOCUMENT,
    TOOL_SUMMARIZE_CORPUS,
    TOOL_PROPOSE_DOCUMENT_EDIT,
    TOOL_RENAME_FILE,
    TOOL_DELETE_FILE,
    TOOL_MOVE_FILE,
})

# ---------------------------------------------------------------------------
# Return types (structured; same shape every time)
# ---------------------------------------------------------------------------


class DocumentEntry(TypedDict, total=False):
    """One row in list_documents result."""
    file_path: str
    file_type: str
    filename: str
    chunks_count: int
    content_preview: str
    processing_status: str


class ListDocumentsResult(TypedDict):
    """Return type for list_documents."""
    documents: List[DocumentEntry]
    count: int


class SourceEntry(TypedDict, total=False):
    """One source in search results."""
    file_path: str
    relevance_score: float
    content_snippet: str
    chunks_found: int
    file_type: str


class SearchDocumentsResult(TypedDict):
    """Return type for search_documents and search_specific_document."""
    context: str
    chunks: List[str]  # Individual chunks for citations, highlighting, chunk-level reasoning
    sources: List[SourceEntry]
    retrieval_count: int
    rerank_count: int


class SummarizeCorpusResult(TypedDict):
    """Return type for summarize_corpus."""
    summary: str
    document_count: int
    file_type_counts: Dict[str, int]
    date_range: str  # optional; empty string if not available


# ---------------------------------------------------------------------------
# Tool definitions: name, description, when to use, parameter schema
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": TOOL_LIST_DOCUMENTS,
        "description": "List all indexed documents in the current folder. Returns file path, type, chunk count, and a short preview per document.",
        "when_to_use": "Use when the user asks what files/documents exist, what is in the folder, list all documents, or show me the files. Do NOT use for searching document content.",
        "parameters": {},
        "returns": "ListDocumentsResult",
    },
    {
        "name": TOOL_SEARCH_DOCUMENTS,
        "description": "Search across all indexed documents for the given query. Returns relevant text chunks and source metadata. The query must be explicit (e.g. after rewriting pronouns like 'that' or 'it' to the document name).",
        "when_to_use": "Use for factual questions, summaries, or when the user asks about content across multiple files. Use when the question is about what documents say, not which files exist.",
        "parameters": {
            "query": {
                "type": "string",
                "description": "The search query. Must be rewritten so it contains no unresolved pronouns (e.g. 'when was BIP-12046 delivered' not 'when was that delivered').",
                "required": True,
            },
        },
        "returns": "SearchDocumentsResult",
    },
    {
        "name": TOOL_SEARCH_SPECIFIC_DOCUMENT,
        "description": "Search only within the named document. Use when the user clearly refers to one file by name or identifier.",
        "when_to_use": "Use when the user asks about a specific file by name: 'what is in report.pdf', 'explain contract.docx', 'summarize that file' (after resolving 'that' to the filename). Do NOT use for 'list all documents' or 'what files do we have'.",
        "parameters": {
            "document_name": {
                "type": "string",
                "description": "Document name or identifier (filename with or without extension, e.g. 'report.pdf' or 'report').",
                "required": True,
            },
        },
        "returns": "SearchDocumentsResult",
    },
    {
        "name": TOOL_SUMMARIZE_CORPUS,
        "description": "Get a short summary of the folder: document count, breakdown by file type, and optional date range. No search; uses precomputed metadata.",
        "when_to_use": "Use with list_documents when the user wants an overview, 'what kind of files', or 'explain our files'. Do NOT use for searching inside document content.",
        "parameters": {},
        "returns": "SummarizeCorpusResult",
    },
    {
        "name": TOOL_RENAME_FILE,
        "description": "Rename a file in the indexed folder.",
        "when_to_use": "Use when the user asks to rename a file. Requires the current filename and the desired new filename.",
        "parameters": {
            "document_name": {
                "type": "string",
                "description": "Current filename (e.g. 'old_name.docx').",
                "required": True,
            },
            "new_name": {
                "type": "string",
                "description": "New filename including extension (e.g. 'new_name.docx'). Must not contain path separators.",
                "required": True,
            },
        },
        "returns": "FileOpResult",
    },
    {
        "name": TOOL_DELETE_FILE,
        "description": "Permanently delete a file from the indexed folder. This cannot be undone.",
        "when_to_use": "Use ONLY when the user explicitly confirms they want to permanently delete a file. Always confirm with the user before calling this tool.",
        "parameters": {
            "document_name": {
                "type": "string",
                "description": "Filename to delete (e.g. 'old_report.pdf').",
                "required": True,
            },
        },
        "returns": "FileOpResult",
    },
    {
        "name": TOOL_MOVE_FILE,
        "description": "Move a file to a different folder within the indexed directory.",
        "when_to_use": "Use when the user asks to move a file to another folder. Use list_documents first to identify the exact destination folder path.",
        "parameters": {
            "document_name": {
                "type": "string",
                "description": "Filename to move (e.g. 'report.pdf').",
                "required": True,
            },
            "destination_folder": {
                "type": "string",
                "description": "Name or partial path of the destination folder (e.g. 'Reports' or 'Archive/2025'). Use list_documents to find exact folder names.",
                "required": True,
            },
        },
        "returns": "FileOpResult",
    },
    {
        "name": TOOL_PROPOSE_DOCUMENT_EDIT,
        "description": (
            "Propose an edit to a .txt or .docx file. Reads the file, generates a structured "
            "find/replace diff, and presents it to the user for review before anything is written. "
            "The user must confirm before any change is applied."
        ),
        "when_to_use": (
            "Use when the user asks to modify, update, edit, change, fix, or rewrite content "
            "in a specific file. Only works with .txt and .docx files."
        ),
        "parameters": {
            "document_name": {
                "type": "string",
                "description": "Name of the file to edit (e.g. 'contract.docx', 'notes.txt').",
                "required": True,
            },
            "instruction": {
                "type": "string",
                "description": (
                    "Clear, specific description of what to change. "
                    "Example: 'change all occurrences of Net 30 to Net 15'."
                ),
                "required": True,
            },
        },
        "returns": "EditProposalResult",
    },
]

# ---------------------------------------------------------------------------
# JSON schema for planner / LLM tool-calling (strict validation)
# Allows multiple tools per turn for queries like "what files do we have and what are they about".
# ---------------------------------------------------------------------------

TOOL_CALL_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {
            "type": "string",
            "enum": list(VALID_TOOL_NAMES),
            "description": "One of: list_documents, search_documents, search_specific_document, summarize_corpus, propose_document_edit, rename_file, delete_file, move_file",
        },
        "query": {
            "type": "string",
            "description": "Required when tool is search_documents.",
        },
        "document_name": {
            "type": "string",
            "description": "Required for search_specific_document, propose_document_edit, rename_file, delete_file, move_file.",
        },
        "new_name": {
            "type": "string",
            "description": "Required when tool is rename_file. The new filename including extension.",
        },
        "destination_folder": {
            "type": "string",
            "description": "Required when tool is move_file. Name or partial path of the destination folder.",
        },
    },
    "required": ["tool"],
    "additionalProperties": False,
}

TOOLS_SCHEMA = {
    "type": "object",
    "properties": {
        "tools": {
            "type": "array",
            "description": "One or more tool calls. E.g. list_documents + summarize_corpus for 'what files do we have and what are they about'.",
            "items": TOOL_CALL_ITEM_SCHEMA,
            "minItems": 1,
        },
    },
    "required": ["tools"],
    "additionalProperties": False,
}


def get_tools_for_planner() -> List[Dict[str, Any]]:
    """
    Return tool definitions in a form suitable for planner prompts or
    LLM tool-calling (e.g. OpenAI function format or a simple list with
    name, description, parameters).
    """
    return list(TOOL_DEFINITIONS)


def get_openai_format_tools() -> List[Dict[str, Any]]:
    """
    Return tool definitions in OpenAI/Groq chat completions format.
    Used for single-loop tool calling (Phase B.3).
    """
    openai_tools: List[Dict[str, Any]] = []
    for t in TOOL_DEFINITIONS:
        name = t["name"]
        desc = t.get("description", "") or ""
        when = t.get("when_to_use", "")
        if when:
            desc = f"{desc} {when}".strip()
        params = t.get("parameters") or {}
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for param_name, param_spec in params.items():
            if isinstance(param_spec, dict):
                properties[param_name] = {
                    "type": param_spec.get("type", "string"),
                    "description": param_spec.get("description", ""),
                }
                if param_spec.get("required"):
                    required.append(param_name)
        openai_tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required if required else [],
                },
            },
        })
    return openai_tools


def validate_tool_call(
    tool: str,
    query: str | None = None,
    name: str | None = None,
    document_name: str | None = None,
) -> tuple[bool, str]:
    """
    Validate a single tool call. Returns (valid, error_message).
    Use for guardrails before executing the tool.
    For search_specific_document, pass document_name= (or name= for backward compat).
    """
    if tool not in VALID_TOOL_NAMES:
        return False, f"Unknown tool: {tool}"
    if tool == TOOL_SEARCH_DOCUMENTS:
        if not query or not str(query).strip():
            return False, "search_documents requires a non-empty 'query'"
    if tool == TOOL_SEARCH_SPECIFIC_DOCUMENT:
        doc_name = document_name or name
        if not doc_name or not str(doc_name).strip():
            return False, "search_specific_document requires a non-empty 'document_name'"
    if tool == TOOL_PROPOSE_DOCUMENT_EDIT:
        doc_name = document_name or name
        if not doc_name or not str(doc_name).strip():
            return False, "propose_document_edit requires a non-empty 'document_name'"
    return True, ""


def validate_tool_calls(tool_calls: List[Dict[str, Any]]) -> tuple[bool, List[str]]:
    """
    Validate a list of tool calls (planner output with multiple tools).
    Returns (all_valid, list of error messages per invalid call).
    """
    errors: List[str] = []
    for i, call in enumerate(tool_calls):
        if not isinstance(call, dict):
            errors.append(f"tools[{i}]: must be an object")
            continue
        tool = call.get("tool")
        if not tool:
            errors.append(f"tools[{i}]: missing 'tool'")
            continue
        ok, err = validate_tool_call(
            tool,
            query=call.get("query"),
            name=call.get("name"),
            document_name=call.get("document_name"),
        )
        if not ok:
            errors.append(f"tools[{i}]: {err}")
    return len(errors) == 0, errors
