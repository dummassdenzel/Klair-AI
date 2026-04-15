"""
QueryPipelineService — owns the entire query execution pipeline.

Responsibilities:
- Route queries: tool-calling loop (Groq), two-step planner (Ollama/Gemini), legacy
  classifier fallback.
- Expose the tool layer (list_documents, search_documents, search_specific_document,
  summarize_corpus) used by both the tool-calling and planner paths.
- Build conversation history with lazy LLM-based summarization.
- Expose query() and query_stream() as the final public entry points.

Dependencies injected via constructor:
  llm_service, embedding_service, router, retrieval_service (RetrievalService)
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

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
    get_openai_format_tools,
    get_tools_for_planner,
    validate_tool_call,
    validate_tool_calls,
)
from ..routing import Router, Route
from .retrieval_service import RetrievalService


logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_QUERY = 4
TOOL_EXECUTION_TIMEOUT_SECONDS = 10


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
        "When the user asks for 'related' documents or 'other files related to X', use search_documents with a "
        "descriptive query (e.g. 'BIP-12046 related documents' or 'documents related to BIP-12046 receipt delivery'), "
        "not just the document identifier. "
        "Citation format: when citing list_documents or summarize_corpus results, use [Folder Overview] or [Document List], "
        "not [Document: list_documents]. When citing search results that mention a specific file, use [Document: filename]."
    )

    PLANNER_MAX_TOKENS = 400

    def __init__(
        self,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        router: Router,
        retrieval_service: RetrievalService,
    ) -> None:
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self.router = router
        self.retrieval = retrieval_service
        self._summary_cache: Dict[int, Tuple[int, str]] = {}

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

        return QueryResult(
            message=text,
            sources=result["sources"],
            response_time=round(asyncio.get_event_loop().time() - start_time, 3),
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
            return

        yield (
            "done",
            {
                "message": text,
                "response_time": round(asyncio.get_event_loop().time() - start_time, 3),
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

        Classifier pre-filter (planner path only)
        -----------------------------------------
        The QueryClassifier is pure heuristic (regex + word matching — zero LLM
        calls). For non-search routes we short-circuit before the planner, saving
        one full LLM round-trip:

          GREETING / GENERAL   → _generate_direct_response()  (1 call instead of 2)
          DOCUMENT_LISTING     → get_document_listing()        (0 LLM calls)
          DOCUMENT_SEARCH      → planner as before             (2 calls, unchanged)

        The tool-calling path (Groq) already handles this natively.
        """
        start_time = asyncio.get_event_loop().time()

        if self.llm_service.supports_tool_calling():
            return await self._pipeline_tool_loop(question, conversation_history, start_time)

        route_result = await self.router.resolve(question, conversation_history)

        if route_result.route in (Route.GREETING, Route.GENERAL):
            logger.info(
                "Pre-filter short-circuit: %s → direct response (no planner call)",
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

        if route_result.route == Route.DOCUMENT_LISTING:
            logger.info("Pre-filter short-circuit: document_listing → DB query (no planner call)")
            result = await self.retrieval.get_document_listing(question=question)
            return {
                "action": "direct",
                "answer": result.message,
                "sources": result.sources,
                "query_type": route_result.query_type,
                "retrieval_count": getattr(result, "retrieval_count", 0) or 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        try:
            return await self._pipeline_planner(question, conversation_history, start_time)
        except Exception as e:
            logger.warning("Planner path failed: %s; falling back to legacy classifier", e)
        return await self._pipeline_legacy(question, conversation_history, start_time)

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
                }
            )
        return {"documents": documents, "count": len(documents)}

    async def run_tool_search_documents(self, query: str) -> Optional[SearchDocumentsResult]:
        """Tool: search_documents. Single hybrid retrieval + rerank; returns context and sources."""
        if not query or not str(query).strip():
            return None
        embedding = self.embedding_service.encode_single_text(query.strip())
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
        embedding = self.embedding_service.encode_single_text(query)
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

    async def run_tool(
        self,
        tool: str,
        *,
        query: Optional[str] = None,
        name: Optional[str] = None,
        document_name: Optional[str] = None,
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
            ):
                continue
            args_str = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Tool arguments parse failed for %s: %s", name, e)
                args = {}
            call: Dict[str, Any] = {"tool": name}
            if name == TOOL_SEARCH_DOCUMENTS:
                call["query"] = args.get("query") or ""
            if name == TOOL_SEARCH_SPECIFIC_DOCUMENT:
                call["document_name"] = args.get("document_name") or args.get("name") or ""
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
        """Shared pipeline for native tool-calling providers (e.g. Groq)."""
        from config import settings

        max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
        messages = self._build_agent_messages(question, conversation_history)
        tools = get_openai_format_tools()

        content, raw_tool_calls = await self.llm_service.chat_with_tools(
            messages, tools, max_tokens=max_tokens
        )

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

        results_by_index = await self._execute_tool_calls(our_calls)
        tool_results = [
            {"tool": our_calls[i].get("tool"), "result": results_by_index[i]}
            for i in range(len(our_calls))
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

    # ------------------------------------------------------------------
    # Two-step planner fallback (Ollama, Gemini)
    # ------------------------------------------------------------------

    def _build_planner_prompt(
        self,
        question: str,
        conversation_history: List[Dict[str, Any]],
    ) -> str:
        """Build prompt for planner LLM: output JSON only with tool choice(s)."""
        tools_desc = []
        for t in get_tools_for_planner():
            name = t.get("name", "")
            desc = t.get("description", "")
            when = t.get("when_to_use", "")
            line = f"- {name}: {desc} {when}".strip()
            if name == TOOL_SEARCH_DOCUMENTS:
                line += ' Include "query" with the search text.'
            if name == TOOL_SEARCH_SPECIFIC_DOCUMENT:
                line += ' Include "document_name" with the file name or identifier.'
            tools_desc.append(line)
        tools_text = "\n".join(tools_desc)
        history_snippet = ""
        if conversation_history:
            recent = conversation_history[-4:]
            parts = []
            for h in recent:
                role = h.get("role", "user")
                content = (h.get("content") or "")[:200].strip()
                if content:
                    parts.append(f"{role}: {content}")
            if parts:
                history_snippet = "Recent conversation:\n" + "\n".join(parts) + "\n\n"
        return (
            "You are a planner for a document assistant. Output ONLY valid JSON, no other text.\n\n"
            f"Available tools:\n{tools_text}\n\n"
            "Rules: If the user asks what files or documents exist, or for an overview of the folder, "
            "use list_documents and/or summarize_corpus; do not use search_documents for that. "
            "Use search_specific_document when the user names a file. Use search_documents only for "
            "factual questions about content or \"related documents\". For greetings or small talk output empty tools.\n"
            'Output format: {"tools": [{"tool": "tool_name", "query": "..." or "document_name": "..." as needed}]}'
            ' or {"tools": []} for no tools.\n\n'
            f"{history_snippet}User: {question}\n\nJSON output:"
        )

    def _parse_planner_output(self, response: str) -> Optional[List[Dict[str, Any]]]:
        """Parse planner LLM response into list of tool calls. Returns None on parse failure."""
        if not response or not response.strip():
            return None
        import re

        text = response.strip()
        if "```" in text:
            m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
            if m:
                text = m.group(1)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Planner output not valid JSON: %s", text[:200])
            return None
        if not isinstance(data, dict):
            return None
        tools = data.get("tools")
        if tools is None or not isinstance(tools, list):
            return None
        out: List[Dict[str, Any]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = item.get("tool")
            if name not in (
                TOOL_LIST_DOCUMENTS,
                TOOL_SEARCH_DOCUMENTS,
                TOOL_SEARCH_SPECIFIC_DOCUMENT,
                TOOL_SUMMARIZE_CORPUS,
            ):
                continue
            call: Dict[str, Any] = {"tool": name}
            if name == TOOL_SEARCH_DOCUMENTS:
                call["query"] = item.get("query") or ""
            if name == TOOL_SEARCH_SPECIFIC_DOCUMENT:
                call["document_name"] = item.get("document_name") or item.get("name") or ""
            out.append(call)
        return out

    async def _get_safe_tool_calls_from_classifier(
        self,
        question: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Safe default: when planner output is invalid, use classifier to choose a safe
        tool set. Prevents blindly executing a mismatched tool.
        """
        try:
            route_result = await self.router.resolve(question, conversation_history or [])
        except Exception as e:
            logger.warning("Router failed for safe default: %s; using no tools", e)
            return []
        route = route_result.route
        if route in (Route.GREETING, Route.GENERAL):
            return []
        if route == Route.DOCUMENT_LISTING:
            return [{"tool": TOOL_LIST_DOCUMENTS}, {"tool": TOOL_SUMMARIZE_CORPUS}]
        return [{"tool": TOOL_SEARCH_DOCUMENTS, "query": question}]

    def _format_tool_results_for_answer(self, tool_results: List[Dict[str, Any]]) -> str:
        """Format tool results as a single context string for the answer LLM."""
        if not tool_results:
            return "No document tools were used. Answer the user directly based on general knowledge."
        parts = []
        for tr in tool_results:
            tool_name = tr.get("tool", "")
            result = tr.get("result") or {}
            if result.get("tool_error"):
                parts.append(f"[{tool_name}]: Error - {result.get('message', 'unknown')}")
                continue
            if tool_name == TOOL_LIST_DOCUMENTS:
                docs = result.get("documents") or []
                count = result.get("count", 0)
                lines = [f"Document list ({count} items):"] + [
                    f"- {d.get('filename', d.get('file_path', ''))} ({d.get('file_type', '')})"
                    for d in docs[:50]
                ]
                if count > 50:
                    lines.append(f"... and {count - 50} more.")
                parts.append("\n".join(lines))
            elif tool_name == TOOL_SUMMARIZE_CORPUS:
                parts.append(f"[Folder overview]\n{result.get('summary', '')}")
            elif tool_name in (TOOL_SEARCH_DOCUMENTS, TOOL_SEARCH_SPECIFIC_DOCUMENT):
                parts.append(result.get("context", ""))
            else:
                parts.append(json.dumps(result, default=str)[:2000])
        return CONTEXT_CHUNK_SEP.join(parts)

    async def _pipeline_planner(
        self,
        question: str,
        conversation_history: List[Dict[str, Any]],
        start_time: float,
    ) -> Dict[str, Any]:
        """Two-step planner path (Ollama, Gemini)."""
        from .llm.provider_adapters import PROMPT_TYPE_CLASSIFICATION

        prompt = self._build_planner_prompt(question, conversation_history)
        planner_response = await self.llm_service.generate_simple(
            prompt,
            prompt_type=PROMPT_TYPE_CLASSIFICATION,
            max_completion_tokens=self.PLANNER_MAX_TOKENS,
        )
        tool_calls = self._parse_planner_output(planner_response)

        if tool_calls is None or (tool_calls and not validate_tool_calls(tool_calls)[0]):
            if tool_calls:
                logger.warning("Planner output failed validation; using safe default from classifier")
            else:
                logger.info("Planner output invalid or empty; using safe default from classifier")
            tool_calls = await self._get_safe_tool_calls_from_classifier(
                question, conversation_history
            )

        if tool_calls:
            results_by_index = await self._execute_tool_calls(tool_calls)
            tool_results = [
                {"tool": tool_calls[i].get("tool"), "result": results_by_index[i]}
                for i in range(len(tool_calls))
            ]
            context = self._format_tool_results_for_answer(tool_results)
            sources = self._collect_sources_from_tool_results(tool_results)
        else:
            context = self._format_tool_results_for_answer([])
            sources = []

        return {
            "action": "rag_context",
            "context": context,
            "sources": sources,
            "query_type": "planner",
            "retrieval_count": len(sources),
            "rerank_count": 0,
            "start_time": start_time,
        }

    async def _pipeline_legacy(
        self,
        question: str,
        conversation_history: List[Dict[str, Any]],
        start_time: float,
    ) -> Dict[str, Any]:
        """Legacy fallback: classifier-based routing. Only reached when the planner path raises."""
        route_task = asyncio.create_task(
            self.router.resolve(question, conversation_history)
        )
        embed_task = asyncio.to_thread(
            self.embedding_service.encode_single_text, question
        )
        route_result = await route_task
        query_embedding = await embed_task
        query_type = route_result.query_type

        if route_result.route in (Route.GREETING, Route.GENERAL):
            response_text = await self._generate_direct_response(question, query_type)
            return {
                "action": "direct",
                "answer": response_text,
                "sources": [],
                "query_type": query_type,
                "retrieval_count": 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        if route_result.route == Route.DOCUMENT_LISTING:
            result = await self.retrieval.get_document_listing(question=question)
            return {
                "action": "direct",
                "answer": result.message,
                "sources": result.sources,
                "query_type": query_type,
                "retrieval_count": getattr(result, "retrieval_count", 0) or 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        rag = await self.retrieval.retrieve_and_build_context(
            question, query_type, query_embedding
        )
        if rag is None:
            return {
                "action": "direct",
                "answer": "I don't have information about that in the current documents.",
                "sources": [],
                "query_type": query_type,
                "retrieval_count": 0,
                "rerank_count": 0,
                "start_time": start_time,
            }

        return {
            "action": "rag_context",
            "context": rag["context"],
            "sources": rag["sources"],
            "query_type": query_type,
            "retrieval_count": rag["retrieval_count"],
            "rerank_count": rag["rerank_count"],
            "start_time": start_time,
        }
