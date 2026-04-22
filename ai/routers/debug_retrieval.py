"""
Debug: inspect hybrid retrieval output and the RAG prompt shell the LLM receives.

Enable with RETRIEVAL_INSPECT_ENABLED=true. Disabled by default (document text exposure).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import settings
from dependencies import require_app_state
from services.routing.routes import Route

from services.query_rewriter import rewrite_with_last_document
from .chat import _build_conversation_history, _rewrite_query_for_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debug", tags=["debug"])


def _truncate(text: str, max_chars: int) -> Tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n\n[... truncated for JSON response ...]", True


class RetrievalInspectRequest(BaseModel):
    message: str = Field(..., min_length=1)
    """User question (same as chat)."""
    session_id: Optional[int] = None
    """If set, conversation history is loaded like /api/chat for accurate prompt preview."""
    mode: Literal["pipeline", "forced_search", "both"] = "both"
    """
    pipeline — run retrieval only when the router would take the document_search RAG path.
    forced_search — always run hybrid retrieval with query_type=document_search (matches search_documents tool).
    both — include both when applicable.
    """
    max_context_chars: int = Field(50_000, ge=2_000, le=200_000)
    """Truncate context / prompt fields in the JSON response (full retrieval still runs)."""


def _strip_rag_for_json(rag: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    ctx = rag.get("context") or ""
    ctx_out, ctx_trunc = _truncate(ctx, max_chars)
    return {
        "context": ctx_out,
        "context_truncated": ctx_trunc,
        "context_char_count": len(ctx),
        "sources": rag.get("sources"),
        "retrieval_count": rag.get("retrieval_count"),
        "rerank_count": rag.get("rerank_count"),
    }


@router.post("/retrieval-inspect")
async def retrieval_inspect(
    body: RetrievalInspectRequest,
    state=Depends(require_app_state),
):
    if not getattr(settings, "RETRIEVAL_INSPECT_ENABLED", False):
        raise HTTPException(
            status_code=404,
            detail="Retrieval inspect is disabled. Set RETRIEVAL_INSPECT_ENABLED=true to enable.",
        )

    proc = state.doc_processor
    raw_message = body.message.strip()
    if not raw_message:
        raise HTTPException(status_code=400, detail="message is empty")

    if body.session_id is not None:
        rewritten = await _rewrite_query_for_session(body.session_id, raw_message)
        history = await _build_conversation_history(body.session_id, proc)
    else:
        rewritten = rewrite_with_last_document(raw_message, None)
        history = []

    route_result = await proc.pipeline.router.resolve(rewritten, history)

    pipeline_routing: Dict[str, Any] = {
        "route": route_result.route.value,
        "query_type": route_result.query_type,
        "would_run_rag_like_legacy": route_result.route == Route.DOCUMENT_SEARCH,
        "notes": [],
    }

    if route_result.route in (Route.GREETING, Route.GENERAL):
        pipeline_routing["notes"].append("Router would short-circuit to a direct LLM reply (no retrieval).")
    elif route_result.route == Route.DOCUMENT_LISTING:
        pipeline_routing["notes"].append("Router would use DB listing / deterministic path, not hybrid chunk retrieval.")

    if proc.llm_service.supports_tool_calling():
        pipeline_routing["notes"].append(
            "LLM provider uses tool-calling: live answers may merge multiple tool results; "
            "this endpoint shows single-pass retrieve_and_build_context (same as search_documents tool)."
        )

    embed = await asyncio.to_thread(proc.pipeline.embedding_service.encode_query, rewritten)

    pipeline_retrieval: Optional[Dict[str, Any]] = None
    pipeline_rag_full: Optional[Dict[str, Any]] = None
    if body.mode in ("pipeline", "both") and pipeline_routing["would_run_rag_like_legacy"]:
        rag = await proc.pipeline.retrieval.retrieve_and_build_context(
            rewritten,
            route_result.query_type,
            embed,
        )
        pipeline_rag_full = rag
        if rag:
            pipeline_retrieval = _strip_rag_for_json(rag, body.max_context_chars)

    forced_retrieval: Optional[Dict[str, Any]] = None
    forced_rag_full: Optional[Dict[str, Any]] = None
    if body.mode in ("forced_search", "both"):
        rag_f = await proc.pipeline.retrieval.retrieve_and_build_context(
            rewritten,
            "document_search",
            embed,
        )
        forced_rag_full = rag_f
        if rag_f:
            forced_retrieval = _strip_rag_for_json(rag_f, body.max_context_chars)

    def _prompt_preview(context: str) -> Dict[str, Any]:
        p_empty = proc.llm_service._build_prompt(rewritten, context, [])
        p_hist = proc.llm_service._build_prompt(rewritten, context, history)
        pe, t1 = _truncate(p_empty, body.max_context_chars)
        ph, t2 = _truncate(p_hist, body.max_context_chars)
        return {
            "prompt_without_history": pe,
            "prompt_without_history_truncated": t1,
            "prompt_with_history": ph,
            "prompt_with_history_truncated": t2,
            "history_message_count": len(history),
        }

    out: Dict[str, Any] = {
        "raw_message": raw_message,
        "rewritten_message": rewritten,
        "routing": pipeline_routing,
        "retrieval_pipeline": pipeline_retrieval,
        "retrieval_forced_document_search": forced_retrieval,
    }

    ctx_full_for_prompt: Optional[str] = None
    if pipeline_rag_full and (pipeline_rag_full.get("context") or "").strip():
        ctx_full_for_prompt = pipeline_rag_full["context"]
        out["rag_prompt_preview_basis"] = "pipeline_retrieval"
    elif forced_rag_full and (forced_rag_full.get("context") or "").strip():
        ctx_full_for_prompt = forced_rag_full["context"]
        out["rag_prompt_preview_basis"] = "forced_document_search"

    if ctx_full_for_prompt is not None:
        out["rag_prompt_preview"] = _prompt_preview(ctx_full_for_prompt)
    else:
        out["rag_prompt_preview"] = None
        out["rag_prompt_preview_basis"] = None

    return out
