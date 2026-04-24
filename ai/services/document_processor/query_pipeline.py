"""
QueryPipelineService — owns the entire query execution pipeline.

Responsibilities:
- Route all queries through the unified agent tool loop (_pipeline_tool_loop).
  Cheap routes (greeting, listing) are short-circuited by the classifier pre-filter
  before any LLM call; document-search queries go through the full agent loop.
- Expose the tool layer (list_documents, search_documents, search_specific_document,
  summarize_corpus).
- Build conversation history with lazy LLM-based summarization.
- Expose query() and query_stream() as the final public entry points.

Dependencies injected via constructor:
  llm_service, embedding_service, router, retrieval_service (RetrievalService)
"""

import asyncio
import json
import logging
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

# Strips the "Page N:" marker that the OCR service prepends to each document's
# extracted text.  Removing it from listing previews lets the LLM see the
# actual document content on the first line instead of a page-counter artifact.
_OCR_PAGE_RE = re.compile(r'^Page \d+:\n?', re.IGNORECASE)

# Strip tool-name citations that some LLMs emit verbatim, e.g. "[search_documents]"
_TOOL_CITATION_RE = re.compile(
    r'\s*\[(search_documents|list_documents|search_specific_document'
    r'|summarize_corpus|propose_document_edit)\]',
    re.IGNORECASE,
)

from .models import QueryResult
from .llm.llm_service import LLMService
from .extraction.embedding_service import EmbeddingService
from .query_config import CONTEXT_CHUNK_SEP
from .corpus_summary import summarize_corpus, corpus_metadata_from_documents
from .tools.contract import (
    ListDocumentsResult,
    SearchDocumentsResult,
    SummarizeCorpusResult,
    TOOL_LIST_DOCUMENTS,
    TOOL_SEARCH_DOCUMENTS,
    TOOL_SEARCH_SPECIFIC_DOCUMENT,
    TOOL_SUMMARIZE_CORPUS,
    TOOL_PROPOSE_DOCUMENT_EDIT,
    get_openai_format_tools,
    validate_tool_call,
    validate_tool_calls,
)
from ..routing import Router, Route
from .retrieval_service import RetrievalService


logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_QUERY = 4
TOOL_EXECUTION_TIMEOUT_SECONDS = 30
LLM_TOOL_CALL_TIMEOUT_SECONDS = 60


class QueryPipelineService:
    """
    Owns query routing, tool execution, and response generation.

    After construction the orchestrator wires this service to retrieval_service so
    all document look-ups are delegated there, keeping this class free of any
    storage or indexing concerns.
    """

    AGENT_SYSTEM_MESSAGE = (
        "You are a helpful document assistant. The user has selected a folder; you have access to tools "
        "to list documents, search across them, search within a specific document, or get a folder summary. "
        "Use the tools when the user asks about files, document content, or the folder. "
        "For greetings or small talk (e.g. 'what's up?', 'hello'), respond directly without calling tools. "
        "When the user asks what files exist or for an overview, use list_documents and/or summarize_corpus; "
        "do not use search_documents for that. When the user asks about a specific file by name, use "
        "search_specific_document with that name. "
        "TOOL SELECTION RULES — read carefully:\n"
        "• list_documents → use when the user wants to ENUMERATE or COUNT documents by category/type "
        "(e.g. 'how many reports do we have', 'list all contracts', 'show me all invoices'). "
        "The returned list includes [Type:] labels and content previews so you can classify and count documents. "
        "DO NOT use search_documents or summarize_corpus for counting documents.\n"
        "• search_documents → use when the user needs to EXTRACT SPECIFIC VALUES or DATA from inside "
        "documents (e.g. 'what is the total amount', 'find all mentions of X', 'what does the agreement say about Y'). "
        "For value/amount queries you MUST use search_documents with a targeted content query — "
        "the document list only shows brief previews and does NOT contain detailed figures. "
        "If a value query also requires knowing which documents are relevant, call list_documents FIRST "
        "then search_documents for the actual values from each relevant document.\n"
        "• search_specific_document → use when the user names a specific file and wants its content.\n"
        "• summarize_corpus → use only for a general high-level overview/summary of the folder.\n"
        "• propose_document_edit → use when the user wants to MODIFY, UPDATE, EDIT, CHANGE, or FIX "
        "content in a specific file. Only .txt and .docx files are supported. "
        "Pass the exact filename and a clear instruction describing what to change. "
        "The user will review and confirm before anything is written.\n"
        "When the user asks for 'related' documents or 'other files related to X', use search_documents with a "
        "descriptive query, not just the document identifier. "
        "Citation format: when citing list_documents or summarize_corpus results, use [Folder Overview] or [Document List], "
        "not [Document: list_documents]. When citing search results that mention a specific file, use [Document: filename]. "
        "CRITICAL — document type classification rules (follow in order): "
        "1. If a document has a [Type: ...] label → that IS its type. "
        "2. If no [Type:] label → infer the document type from its content preview or title as a whole. "
        "Classify based on what the document IS, not what it merely mentions or references. "
        "3. NEVER classify a document based on a keyword that appears only as a column header or table value "
        "referencing another document — check the document's own title or prominent heading first. "
        "IMPORTANT — NEVER write tool names in brackets in your response. Do not write "
        "[search_documents], [list_documents], [search_specific_document], [summarize_corpus], "
        "or [propose_document_edit] anywhere in your answer.\n"
        "KNOWLEDGE ENRICHMENT — when the user asks a comparative, contextual, or benchmarking question "
        "(e.g. 'how does this compare to industry average?', 'is this margin good?', 'what's typical for this?'), "
        "you MUST do two things: (1) answer using the retrieved document data as the primary source, "
        "(2) enrich the answer with relevant general knowledge from your training — industry benchmarks, "
        "typical ranges, common standards — to give the user useful context beyond the documents. "
        "Clearly distinguish: present document findings first, then add context introduced with a phrase like "
        "'For context, industry benchmarks suggest...' or 'Generally speaking, ...' "
        "Do NOT say 'this information is not in the documents' and stop there — always provide useful context "
        "when general knowledge is relevant to the question."
    )

    def __init__(
        self,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        router: Router,
        retrieval_service: RetrievalService,
        edit_service: Optional[Any] = None,
    ) -> None:
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self.router = router
        self.retrieval = retrieval_service
        self.edit_service = edit_service
        self._summary_cache: OrderedDict = OrderedDict()  # session_id → (older_count, summary_text); LRU, max 200
        self._suggestions_cache: Dict[str, List[str]] = {}  # directory → suggestions

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def query(
        self,
        question: str,
        max_results: int = 15,
        conversation_history: list = None,
    ) -> QueryResult:
        """Query the document index (buffered, non-streaming)."""
        history = conversation_history or []
        try:
            result = await self._run_shared_pipeline(question, history)
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return QueryResult(
                message=f"Sorry, I encountered an error while processing your query: {str(e)}",
                sources=[],
                response_time=0.0,
                query_type="error",
                retrieval_count=0,
                rerank_count=0,
            )

        start_time = result["start_time"]
        action = result["action"]

        if action == "direct":
            text = result["answer"]
        elif action == "chat_messages":
            parts: List[str] = []
            async for delta in self.llm_service.chat_messages_stream(
                result["messages"], max_tokens=result["max_tokens"]
            ):
                parts.append(delta)
            text = "".join(parts).strip() or "I couldn't generate a response."
        else:  # rag_context
            text = await self.llm_service.generate_response(
                question, result["context"], conversation_history=history
            )

        text = _TOOL_CITATION_RE.sub("", text).strip()
        return QueryResult(
            message=text,
            sources=result["sources"],
            response_time=round(asyncio.get_running_loop().time() - start_time, 3),
            query_type=result["query_type"],
            retrieval_count=result["retrieval_count"],
            rerank_count=result["rerank_count"],
        )

    async def query_stream(
        self,
        question: str,
        max_results: int = 15,
        conversation_history: list = None,
    ) -> AsyncIterator[Tuple[str, Any]]:
        """Same pipeline as query() but yields SSE events: meta → token*N → done."""
        history = conversation_history or []
        try:
            result = await self._run_shared_pipeline(question, history)
        except Exception as e:
            logger.error(f"Query stream failed: {e}")
            yield ("error", {"detail": str(e)})
            return

        start_time = result["start_time"]
        action = result["action"]

        yield ("meta", {"sources": result["sources"], "query_type": result["query_type"]})

        # Emit any edit proposals before the text stream so the frontend can render
        # the proposal card alongside the AI response text.
        for proposal in result.get("edit_proposals", []):
            yield ("edit_proposal", proposal)

        text = ""
        try:
            if action == "direct":
                text = result["answer"]
                yield ("token", text)
            elif action == "chat_messages":
                parts: List[str] = []
                async for delta in self.llm_service.chat_messages_stream(
                    result["messages"], max_tokens=result["max_tokens"]
                ):
                    parts.append(delta)
                    yield ("token", delta)
                text = "".join(parts).strip() or "I couldn't generate a response."
            else:  # rag_context
                parts = []
                async for delta in self.llm_service.generate_response_stream(
                    question, result["context"], conversation_history=history
                ):
                    parts.append(delta)
                    yield ("token", delta)
                text = "".join(parts)
        except Exception as e:
            logger.error(f"Query stream generation failed: {e}")
            yield ("error", {"detail": str(e)})
            # Fall through — always emit done so the frontend has a terminal event.

        text = _TOOL_CITATION_RE.sub("", text).strip()
        yield (
            "done",
            {
                "message": text,
                "response_time": round(asyncio.get_running_loop().time() - start_time, 3),
                "query_type": result["query_type"],
                "retrieval_count": result["retrieval_count"],
                "rerank_count": result["rerank_count"],
            },
        )

    async def build_conversation_history(
        self,
        message_pairs: List[Dict[str, str]],
        session_id: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        Build LLM-ready conversation history with lazy summarization.

        Short conversations (≤ max_recent_pairs) are returned verbatim.
        Long conversations emit a cached summary of older turns as a system
        message, followed by the most recent turns verbatim.

        The summary is recomputed at most once per new older_pair added to the
        history; subsequent queries with the same older_count hit the cache.
        """
        if not message_pairs:
            return []

        max_recent_pairs = 6

        if len(message_pairs) <= max_recent_pairs:
            history: List[Dict[str, str]] = []
            for pair in message_pairs:
                user_msg = (pair.get("user") or "").strip()
                ai_msg = (pair.get("assistant") or "").strip()
                if user_msg:
                    history.append({"role": "user", "content": user_msg})
                if ai_msg:
                    history.append({"role": "assistant", "content": ai_msg})
            return history

        older_pairs = message_pairs[:-max_recent_pairs]
        recent_pairs = message_pairs[-max_recent_pairs:]
        older_count = len(older_pairs)

        summary_text = ""
        if session_id is not None and session_id in self._summary_cache:
            self._summary_cache.move_to_end(session_id)
        cached = self._summary_cache.get(session_id) if session_id is not None else None
        if cached is not None and cached[0] == older_count:
            summary_text = cached[1]
            logger.debug(
                "Conversation summary cache hit for session %s (older_count=%s)",
                session_id,
                older_count,
            )
        else:
            try:
                lines: List[str] = []
                for pair in older_pairs:
                    user_msg = (pair.get("user") or "").strip()
                    ai_msg = (pair.get("assistant") or "").strip()
                    if user_msg:
                        lines.append(f"User: {user_msg}")
                    if ai_msg:
                        lines.append(f"Assistant: {ai_msg}")
                transcript = "\n".join(lines)

                max_input_chars = 4000
                if len(transcript) > max_input_chars:
                    transcript = transcript[-max_input_chars:]

                prompt = (
                    "Summarize the following conversation between a user and an AI assistant.\n"
                    "Focus on key facts about the user's documents, goals, constraints, and decisions.\n"
                    "Write 3–6 short bullet points.\n\n"
                    f"Conversation:\n{transcript}"
                )
                summary = await self.llm_service.generate_simple(
                    prompt,
                    prompt_type="short_direct",
                    max_completion_tokens=256,
                )
                summary_text = (summary or "").strip()
                logger.debug(
                    "Conversation summary generated for session %s (older_count=%s)",
                    session_id,
                    older_count,
                )
            except Exception as e:
                logger.warning(
                    "Conversation summarization failed, falling back to recent turns only: %s", e
                )
                summary_text = ""

            if session_id is not None:
                self._summary_cache[session_id] = (older_count, summary_text)
                if len(self._summary_cache) > 200:
                    self._summary_cache.popitem(last=False)

        history = []
        if summary_text:
            history.append(
                {"role": "system", "content": "Summary of earlier conversation:\n" + summary_text}
            )

        for pair in recent_pairs:
            user_msg = (pair.get("user") or "").strip()
            ai_msg = (pair.get("assistant") or "").strip()
            if user_msg:
                history.append({"role": "user", "content": user_msg})
            if ai_msg:
                history.append({"role": "assistant", "content": ai_msg})

        return history

    # ------------------------------------------------------------------
    # Suggested queries
    # ------------------------------------------------------------------

    async def generate_suggestions(self, directory: str = "") -> List[str]:
        """Return 4 context-aware suggested questions based on the indexed documents."""
        cache_key = directory or "_default"
        if cache_key in self._suggestions_cache:
            return self._suggestions_cache[cache_key]

        try:
            return await asyncio.wait_for(
                self._do_generate_suggestions(cache_key), timeout=20.0
            )
        except asyncio.TimeoutError:
            logger.warning("Suggestion generation timed out")
            return []
        except Exception as e:
            logger.warning("Suggestion generation failed: %s", e)
            return []

    async def _do_generate_suggestions(self, cache_key: str) -> List[str]:
        docs_result = await self.run_tool_list_documents()
        if not docs_result or not docs_result.get("documents"):
            return []

        docs = docs_result["documents"][:15]
        doc_lines: List[str] = []
        for doc in docs:
            name = doc.get("filename", "")
            ftype = (doc.get("file_type") or "").upper()
            preview = _OCR_PAGE_RE.sub("", doc.get("content_preview") or "")[:80].strip()
            doc_lines.append(f"- {name} ({ftype}){': ' + preview if preview else ''}")

        doc_summary = "\n".join(doc_lines)
        count = docs_result.get("count", len(docs))

        prompt = (
            f"A user has indexed a folder with {count} document(s):\n\n"
            f"{doc_summary}\n\n"
            "Generate exactly 4 short, natural questions the user would genuinely want to ask.\n"
            "Rules:\n"
            "- Mix: one overview, one specific content, one cross-document comparison, one detail/value question\n"
            "- Write as the user would type them — casual and natural\n"
            "- Each question must be under 12 words and end with a question mark\n"
            "- Return ONLY 4 lines, no numbering, bullets, or extra text\n\n"
            "Questions:"
        )

        response = await self.llm_service.generate_simple(
            prompt, prompt_type="short_direct", max_completion_tokens=150
        )
        lines = [
            l.strip().lstrip("•-–—*123456789. ").strip('"').strip("'")
            for l in (response or "").split("\n")
            if l.strip()
        ]
        suggestions = [l for l in lines if len(l) > 8 and "?" in l][:4]
        if suggestions:
            self._suggestions_cache[cache_key] = suggestions
        return suggestions

    def invalidate_suggestions_cache(self, directory: str = "") -> None:
        self._suggestions_cache.pop(directory or "_default", None)

    async def generate_follow_up_suggestions(self, question: str, answer: str) -> List[str]:
        """Return 2-3 short follow-up questions based on the last Q&A exchange."""
        if not question or not answer:
            return []
        try:
            return await asyncio.wait_for(
                self._do_generate_follow_ups(question, answer), timeout=12.0
            )
        except asyncio.TimeoutError:
            logger.warning("Follow-up suggestion generation timed out")
            return []
        except Exception as e:
            logger.warning("Follow-up suggestion generation failed: %s", e)
            return []

    async def _do_generate_follow_ups(self, question: str, answer: str) -> List[str]:
        # Truncate answer so prompt stays compact
        answer_snippet = answer[:600].strip()
        prompt = (
            f'A user asked: "{question}"\n'
            f'The assistant answered: "{answer_snippet}"\n\n'
            "Suggest exactly 3 short follow-up questions the user might want to ask next.\n"
            "Rules:\n"
            "- Each question must be under 12 words\n"
            "- Naturally follow from the answer — dive deeper, related angle, or comparison\n"
            "- Write as the user would type them — casual and natural\n"
            "- Return ONLY 3 lines, no numbering, bullets, or extra text\n\n"
            "Questions:"
        )
        response = await self.llm_service.generate_simple(
            prompt, prompt_type="short_direct", max_completion_tokens=120
        )
        lines = [
            l.strip().lstrip("•-–—*123456789. ").strip('"').strip("'")
            for l in (response or "").split("\n")
            if l.strip()
        ]
        return [l for l in lines if len(l) > 6 and "?" in l][:3]

    # ------------------------------------------------------------------
    # Shared pipeline
    # ------------------------------------------------------------------

    async def _run_shared_pipeline(
        self,
        question: str,
        conversation_history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Route to the appropriate pipeline and return a unified pipeline-result dict.
        Both query() and query_stream() call this; they differ only in how they
        consume the final LLM generation step described by result["action"].

        Pipeline-result keys
        --------------------
        action          "direct" | "chat_messages" | "rag_context"
        answer          str   (action == "direct" only)
        messages        list  (action == "chat_messages" only)
        max_tokens      int   (action == "chat_messages" only)
        context         str   (action == "rag_context" only)
        sources         list
        query_type      str
        retrieval_count int
        rerank_count    int
        start_time      float

        """
        start_time = asyncio.get_running_loop().time()
        return await self._pipeline_tool_loop(question, conversation_history, start_time)

    # ------------------------------------------------------------------
    # Direct response (greetings / general)
    # ------------------------------------------------------------------

    async def _generate_direct_response(self, question: str, response_type: str) -> str:
        """Generate a direct response without document retrieval (greetings, general queries)."""
        try:
            if response_type == "greeting":
                prompt = (
                    f'You are a friendly AI assistant for a document management system.\n\n'
                    f'User said: "{question}"\n\n'
                    "Respond warmly and briefly (1-2 sentences). Let them know you can help with documents.\n\n"
                    "Your response:"
                )
            else:
                prompt = (
                    f'You are an AI assistant for a document management system.\n\n'
                    f'User asked: "{question}"\n\n'
                    "Answer their question. Your capabilities:\n"
                    "- Search and analyze indexed documents\n"
                    "- Answer questions about specific files\n"
                    "- List and compare documents\n"
                    "- Find information across multiple files\n\n"
                    "Keep your response concise and helpful (2-3 sentences).\n\n"
                    "Your response:"
                )
            return await self.llm_service.generate_simple(prompt, prompt_type="short_direct")
        except Exception as e:
            logger.error(f"Direct response generation failed: {e}")
            return (
                "Hello! I'm your document assistant. I can help you search and analyze your "
                "indexed documents. What would you like to know?"
            )

    # ------------------------------------------------------------------
    # Tool layer
    # ------------------------------------------------------------------

    async def run_tool_list_documents(self) -> ListDocumentsResult:
        """Tool: list_documents. Returns all indexed documents with metadata."""
        all_docs = await self.retrieval.get_all_indexed_docs()
        documents: List[Dict[str, Any]] = []
        for doc in all_docs:
            filename = Path(doc.file_path).name
            preview = (doc.content_preview or "")[:300]
            if len((doc.content_preview or "")) > 300:
                preview += "..."
            documents.append(
                {
                    "file_path": doc.file_path,
                    "file_type": doc.file_type,
                    "filename": filename,
                    "chunks_count": getattr(doc, "chunks_count", 0) or 0,
                    "content_preview": preview,
                    "processing_status": getattr(doc, "processing_status", "indexed"),
                    "document_category": getattr(doc, "document_category", None) or None,
                }
            )
        return {"documents": documents, "count": len(documents)}

    async def run_tool_search_documents(self, query: str) -> Optional[SearchDocumentsResult]:
        """Tool: search_documents. Single hybrid retrieval + rerank; returns context and sources."""
        if not query or not str(query).strip():
            return None
        embedding = self.embedding_service.encode_query(query.strip())
        rag = await self.retrieval.retrieve_and_build_context(
            question=query.strip(),
            query_type="document_search",
            query_embedding=embedding,
        )
        if rag is None:
            return None
        chunks = [s.strip() for s in rag["context"].split(CONTEXT_CHUNK_SEP) if s.strip()]
        return {
            "context": rag["context"],
            "chunks": chunks,
            "sources": rag["sources"],
            "retrieval_count": rag["retrieval_count"],
            "rerank_count": rag["rerank_count"],
        }

    async def run_tool_search_specific_document(
        self, document_name: str
    ) -> Optional[SearchDocumentsResult]:
        """Tool: search_specific_document. Restricts retrieval to the named document."""
        if not document_name or not str(document_name).strip():
            return None
        query = document_name.strip()
        embedding = self.embedding_service.encode_query(query)
        rag = await self.retrieval.retrieve_and_build_context(
            question=query,
            query_type="document_search",
            query_embedding=embedding,
            explicit_filename_override=query,
        )
        if rag is None:
            return None
        chunks = [s.strip() for s in rag["context"].split(CONTEXT_CHUNK_SEP) if s.strip()]
        return {
            "context": rag["context"],
            "chunks": chunks,
            "sources": rag["sources"],
            "retrieval_count": rag["retrieval_count"],
            "rerank_count": rag["rerank_count"],
        }

    async def run_tool_summarize_corpus(self) -> SummarizeCorpusResult:
        """Tool: summarize_corpus. Returns folder summary and metadata."""
        all_docs = await self.retrieval.get_all_indexed_docs()
        metadata = corpus_metadata_from_documents(all_docs)
        summary = summarize_corpus(all_docs)
        date_range_str = ""
        if metadata.get("date_range") and len(metadata["date_range"]) == 2:
            low, high = metadata["date_range"]
            if hasattr(low, "strftime") and hasattr(high, "strftime"):
                try:
                    date_range_str = f"{low.strftime('%b %Y')} – {high.strftime('%b %Y')}"
                except (TypeError, ValueError):
                    pass
        return {
            "summary": summary,
            "document_count": metadata.get("document_count", 0),
            "file_type_counts": metadata.get("file_type_counts") or {},
            "date_range": date_range_str,
        }

    async def run_tool_propose_document_edit(
        self, document_name: str, instruction: str
    ) -> Optional[Dict[str, Any]]:
        """Tool: propose_document_edit. Reads the file, generates a diff, stores the proposal."""
        if not self.edit_service:
            return {"tool_error": True, "message": "Edit service is not available.", "retryable": False}
        if not document_name or not instruction:
            return {"tool_error": True, "message": "document_name and instruction are required.", "retryable": False}

        # Resolve filename → full path via the shared FilenameTrie
        trie = getattr(self.retrieval, "filename_trie", None)
        file_path: Optional[str] = None
        if trie is not None:
            matches = trie.search(document_name.strip(), max_results=1)
            if matches:
                file_path = matches[0]
        if not file_path:
            return {
                "tool_error": True,
                "message": f"Could not find a file matching '{document_name}' in the indexed folder.",
                "retryable": False,
            }

        if not self.edit_service.can_edit(file_path):
            suffix = Path(file_path).suffix.lower()
            return {
                "tool_error": True,
                "message": f"Editing {suffix} files is not supported in Phase 1. Only .txt and .docx are editable.",
                "retryable": False,
            }

        content = self.edit_service.read_for_edit(file_path)
        if content is None:
            return {"tool_error": True, "message": f"Could not read '{document_name}'.", "retryable": False}

        proposal = await self.edit_service.generate_proposal(
            file_path=file_path,
            content=content,
            instruction=instruction,
            llm_service=self.llm_service,
        )
        if proposal is None:
            return {
                "tool_error": True,
                "message": (
                    "Could not generate a valid edit proposal. "
                    "The instruction may be too vague, or the target text was not found."
                ),
                "retryable": False,
            }

        return {"proposal": proposal.to_client_dict(), "summary": proposal.summary}

    async def run_tool(
        self,
        tool: str,
        *,
        query: Optional[str] = None,
        name: Optional[str] = None,
        document_name: Optional[str] = None,
        instruction: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Single entry point for tool execution. Validates, then dispatches."""
        doc_name = document_name or name
        ok, err = validate_tool_call(tool, query=query, name=doc_name, document_name=doc_name)
        if not ok:
            logger.warning("Tool validation failed: %s", err)
            return None
        try:
            if tool == TOOL_LIST_DOCUMENTS:
                return await self.run_tool_list_documents()
            if tool == TOOL_SEARCH_DOCUMENTS:
                return await self.run_tool_search_documents(query or "")
            if tool == TOOL_SEARCH_SPECIFIC_DOCUMENT:
                return await self.run_tool_search_specific_document(doc_name or "")
            if tool == TOOL_SUMMARIZE_CORPUS:
                return await self.run_tool_summarize_corpus()
            if tool == TOOL_PROPOSE_DOCUMENT_EDIT:
                return await self.run_tool_propose_document_edit(doc_name or "", instruction or "")
        except Exception as e:
            logger.error("Tool execution failed for %s: %s", tool, e)
            return None
        return None

    async def run_tools(
        self, tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Execute multiple tool calls in order, skipping invalid ones."""
        ok, errors = validate_tool_calls(tool_calls)
        if not ok:
            for e in errors:
                logger.warning("Tool call validation: %s", e)
        results: List[Dict[str, Any]] = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            tool = call.get("tool")
            if not tool:
                continue
            result = await self.run_tool(
                tool,
                query=call.get("query"),
                name=call.get("name"),
                document_name=call.get("document_name"),
                instruction=call.get("instruction"),
            )
            if result is not None:
                results.append({"tool": tool, "result": result})
        return results

    # ------------------------------------------------------------------
    # Agent loop (native tool-calling providers, e.g. Groq)
    # ------------------------------------------------------------------

    def _build_agent_messages(
        self,
        question: str,
        conversation_history: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build messages for the agent: system + history + user question."""
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.AGENT_SYSTEM_MESSAGE},
        ]
        for h in conversation_history or []:
            role = h.get("role", "user")
            content = h.get("content") or ""
            if not content and "content" in h:
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})
        return messages

    @staticmethod
    def _tool_error_payload(message: str, retryable: bool = False) -> Dict[str, Any]:
        """Structured tool failure payload so the model can reason about failures."""
        return {"tool_error": True, "message": message, "retryable": retryable}

    @staticmethod
    def _format_tool_result_content(tool_name: str, result_payload: Dict[str, Any]) -> str:
        """Format tool result for the LLM; add citation hint for folder-level tools."""
        body = json.dumps(result_payload, default=str)
        if result_payload.get("tool_error"):
            return body
        if tool_name in (TOOL_LIST_DOCUMENTS, TOOL_SUMMARIZE_CORPUS):
            return "Cite this as [Folder Overview] when referring to this information.\n" + body
        return body

    def _parse_groq_tool_calls(
        self, raw_tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert Groq/OpenAI tool_calls to our run_tools format."""
        out: List[Dict[str, Any]] = []
        for tc in raw_tool_calls or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            if name not in (
                TOOL_LIST_DOCUMENTS,
                TOOL_SEARCH_DOCUMENTS,
                TOOL_SEARCH_SPECIFIC_DOCUMENT,
                TOOL_SUMMARIZE_CORPUS,
                TOOL_PROPOSE_DOCUMENT_EDIT,
            ):
                continue
            args_str = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Skipping tool %s — malformed arguments JSON: %s", name, e)
                continue
            call: Dict[str, Any] = {"tool": name}
            if name == TOOL_SEARCH_DOCUMENTS:
                call["query"] = args.get("query") or ""
            if name in (TOOL_SEARCH_SPECIFIC_DOCUMENT, TOOL_PROPOSE_DOCUMENT_EDIT):
                call["document_name"] = args.get("document_name") or args.get("name") or ""
            if name == TOOL_PROPOSE_DOCUMENT_EDIT:
                call["instruction"] = args.get("instruction") or ""
            if name == TOOL_SEARCH_SPECIFIC_DOCUMENT:
                logger.info("Agent tool decision: %s(%s)", name, call.get("document_name", ""))
            elif name == TOOL_SEARCH_DOCUMENTS:
                logger.info(
                    "Agent tool decision: %s(%s)",
                    name,
                    (call.get("query", "") or "")[:80],
                )
            else:
                logger.info("Agent tool decision: %s", name)
            out.append(call)
        return out

    def _collect_sources_from_tool_results(
        self, tool_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract source entries from search tool results for QueryResult.sources."""
        sources: List[Dict[str, Any]] = []
        for tr in tool_results or []:
            result = tr.get("result") or {}
            if "sources" in result:
                sources.extend(result["sources"])
        return sources

    async def _execute_tool_calls(
        self, tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Execute tool calls with timeout/error handling. Returns results in the same order."""
        results = []
        for call in tool_calls:
            try:
                r = await asyncio.wait_for(
                    self.run_tool(
                        call["tool"],
                        query=call.get("query"),
                        document_name=call.get("document_name"),
                        instruction=call.get("instruction"),
                    ),
                    timeout=TOOL_EXECUTION_TIMEOUT_SECONDS,
                )
                results.append(
                    r if r is not None else self._tool_error_payload(
                        "Tool execution failed", retryable=False
                    )
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Tool %s timed out after %s s",
                    call.get("tool"),
                    TOOL_EXECUTION_TIMEOUT_SECONDS,
                )
                results.append(
                    self._tool_error_payload("Tool execution timed out", retryable=True)
                )
            except Exception as e:
                logger.warning("Tool %s failed: %s", call.get("tool"), e)
                results.append(self._tool_error_payload(str(e), retryable=False))
        return results

    async def _pipeline_tool_loop(
        self,
        question: str,
        conversation_history: List[Dict[str, Any]],
        start_time: float,
    ) -> Dict[str, Any]:
        """Unified agent pipeline — the only query path after DR2."""
        from config import settings

        # Classifier pre-filter: resolve route once, handle cheap cases first.
        # Document-listing queries are cheaper via DB than via tool loop (agent
        # tends to pick search_documents for count/list questions, getting top-N
        # chunks instead of the full inventory).
        route_result = await self.router.resolve(question, conversation_history)

        if route_result.route == Route.DOCUMENT_LISTING:
            logger.info("Pre-filter: document_listing → DB query (no agent call)")
            result = await self.retrieval.get_document_listing(question=question)
            return {
                "action": "direct",
                "answer": result.message,
                "sources": result.sources,
                "query_type": "document_listing",
                "retrieval_count": getattr(result, "retrieval_count", 0) or 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        if route_result.route in (Route.GREETING, Route.GENERAL):
            logger.info(
                "Pre-filter: %s → direct response (no tool calls)",
                route_result.query_type,
            )
            response_text = await self._generate_direct_response(question, route_result.query_type)
            return {
                "action": "direct",
                "answer": response_text,
                "sources": [],
                "query_type": route_result.query_type,
                "retrieval_count": 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
        messages = self._build_agent_messages(question, conversation_history)
        tools = get_openai_format_tools()

        try:
            content, raw_tool_calls = await asyncio.wait_for(
                self.llm_service.chat_with_tools(messages, tools, max_tokens=max_tokens),
                timeout=LLM_TOOL_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "chat_with_tools timed out after %ss — provider may be unresponsive",
                LLM_TOOL_CALL_TIMEOUT_SECONDS,
            )
            return {
                "action": "direct",
                "answer": "The AI service is taking too long to respond. Please try again.",
                "sources": [],
                "query_type": "error",
                "retrieval_count": 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        if raw_tool_calls and len(raw_tool_calls) > MAX_TOOL_CALLS_PER_QUERY:
            raw_tool_calls = raw_tool_calls[:MAX_TOOL_CALLS_PER_QUERY]
            logger.warning(
                "Agent returned more than %s tool calls; capping at %s",
                MAX_TOOL_CALLS_PER_QUERY,
                MAX_TOOL_CALLS_PER_QUERY,
            )

        direct_answer = content or "I couldn't generate a response."
        if not raw_tool_calls:
            return {
                "action": "direct",
                "answer": direct_answer,
                "sources": [],
                "query_type": "agent",
                "retrieval_count": 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        our_calls = self._parse_groq_tool_calls(raw_tool_calls)
        if not our_calls:
            return {
                "action": "direct",
                "answer": direct_answer,
                "sources": [],
                "query_type": "agent",
                "retrieval_count": 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        # Separate edit proposals from read calls.
        # Edit proposals don't need a second LLM round-trip — execute and return directly.
        edit_calls = [c for c in our_calls if c.get("tool") == TOOL_PROPOSE_DOCUMENT_EDIT]
        read_calls = [c for c in our_calls if c.get("tool") != TOOL_PROPOSE_DOCUMENT_EDIT]

        edit_proposals: List[Dict[str, Any]] = []
        if edit_calls:
            edit_results = await self._execute_tool_calls(edit_calls)
            for res in edit_results:
                proposal_data = (res or {}).get("proposal")
                if proposal_data:
                    edit_proposals.append(proposal_data)
                elif res and res.get("tool_error"):
                    direct_answer = res.get("message", direct_answer)

        if edit_proposals:
            return {
                "action": "direct",
                "answer": content or "I've prepared the proposed edits. Please review and confirm.",
                "sources": [],
                "query_type": "document_edit",
                "retrieval_count": 0,
                "rerank_count": 0,
                "edit_proposals": edit_proposals,
                "start_time": start_time,
            }

        if not read_calls:
            return {
                "action": "direct",
                "answer": direct_answer,
                "sources": [],
                "query_type": "agent",
                "retrieval_count": 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        results_by_index = await self._execute_tool_calls(read_calls)
        tool_results = [
            {"tool": read_calls[i].get("tool"), "result": results_by_index[i]}
            for i in range(len(read_calls))
        ]
        sources = self._collect_sources_from_tool_results(tool_results)

        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": content or "",
            "tool_calls": raw_tool_calls,
        }
        messages.append(assistant_msg)
        for i, tc in enumerate(raw_tool_calls):
            result_payload = results_by_index[i] if i < len(results_by_index) else {}
            tool_name = our_calls[i].get("tool", "") if i < len(our_calls) else ""
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": self._format_tool_result_content(tool_name, result_payload),
                }
            )

        return {
            "action": "chat_messages",
            "messages": messages,
            "max_tokens": max_tokens,
            "sources": sources,
            "query_type": "agent",
            "retrieval_count": len(sources),
            "rerank_count": 0,
            "start_time": start_time,
        }

