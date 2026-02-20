"""Chat and chat-session endpoints."""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import logging
import json
from datetime import datetime

from schemas.chat import ChatRequest, ChatResponse
from query_cache import get_query_cache_key
from dependencies import db_service, metrics_service, require_app_state
from services.logging_config import log_query_metrics

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _get_or_create_session(session_id: int | None, directory: str, message: str):
    """Resolve an existing session or create a new one."""
    title = f"Chat about: {message[:50]}..."
    if session_id:
        try:
            session = await db_service.get_chat_session_by_id(session_id)
            if session:
                return session
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {e}")
    return await db_service.create_chat_session(directory_path=directory, title=title)


async def _build_conversation_history(session_id: int) -> list:
    try:
        previous = await db_service.get_chat_history(session_id)
        recent = previous[-3:] if len(previous) > 3 else previous
        history = []
        for msg in recent:
            history.append({"role": "user", "content": msg.user_message})
            history.append({"role": "assistant", "content": msg.ai_response})
        return history
    except Exception as e:
        logger.warning(f"Could not fetch conversation history: {e}")
        return []


async def _link_sources_to_session(sources: list, session_id: int) -> None:
    """Link document sources to a chat session (creates fallback records if needed)."""
    async def _link_one(src: dict) -> None:
        file_path = src.get("file_path")
        if not file_path:
            return
        try:
            existing = await db_service.get_document_by_path(file_path)
            if existing:
                await db_service.link_document_to_chat(document_id=existing.id, chat_session_id=session_id)
            else:
                doc = await db_service.store_document_metadata(
                    file_path=file_path,
                    file_hash="",
                    file_type=src.get("file_type", "unknown"),
                    file_size=0,
                    last_modified=datetime.utcnow(),
                    content_preview=(src.get("content_snippet") or "")[:500],
                    chunks_count=src.get("chunks_found", 0),
                )
                await db_service.link_document_to_chat(document_id=doc.id, chat_session_id=session_id)
        except Exception as e:
            logger.error(f"Error linking document {file_path} to chat: {e}")

    if sources:
        await asyncio.gather(*[_link_one(s) for s in sources], return_exceptions=True)


def _record_metrics(
    message: str, query_type: str, response_time: float,
    sources_count: int, retrieval_count: int, rerank_count: int,
    session_id: int, error: bool = False, error_message: str | None = None,
):
    log_query_metrics(
        logger=logger, query=message, query_type=query_type,
        response_time=response_time, sources_count=sources_count,
        retrieval_count=retrieval_count, rerank_count=rerank_count,
        session_id=session_id,
    )
    metrics_service.record_query(
        query_type=query_type,
        response_time_ms=response_time * 1000,
        sources_count=sources_count,
        retrieval_count=retrieval_count,
        rerank_count=rerank_count,
        session_id=session_id,
        query_preview=message[:100],
        error=error,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=ChatResponse)
async def chat(chat_request: ChatRequest, request: Request, state=Depends(require_app_state)):
    """Query the document index with natural language."""
    try:
        chat_session = await _get_or_create_session(
            chat_request.session_id, state.current_directory, chat_request.message
        )

        cache = getattr(state, "query_cache", None)
        cache_key = get_query_cache_key(chat_session.id, chat_request.message) if cache else None
        if cache and cache_key:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.info(f"Query cache hit for session {chat_session.id}")
                return ChatResponse(message=cached["message"], sources=cached["sources"])

        conversation_history = await _build_conversation_history(chat_session.id)
        response = await state.doc_processor.query(
            chat_request.message, conversation_history=conversation_history
        )

        if cache and cache_key:
            cache.set(cache_key, {"message": response.message, "sources": response.sources})

        await db_service.add_chat_message(
            session_id=chat_session.id,
            user_message=chat_request.message,
            ai_response=response.message,
            sources=response.sources,
            response_time=response.response_time,
        )
        await _link_sources_to_session(response.sources, chat_session.id)
        _record_metrics(
            chat_request.message, response.query_type or "unknown",
            response.response_time, len(response.sources),
            response.retrieval_count or 0, response.rerank_count or 0,
            chat_session.id,
        )
        return ChatResponse(message=response.message, sources=response.sources)

    except Exception as e:
        logger.error(f"Query failed: {e}")
        metrics_service.record_query(
            query_type="error", response_time_ms=0, sources_count=0,
            retrieval_count=0, rerank_count=0, error=True, error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(chat_request: ChatRequest, request: Request, state=Depends(require_app_state)):
    """Stream chat response as Server-Sent Events (meta -> token*N -> done)."""
    try:
        chat_session = await _get_or_create_session(
            chat_request.session_id, state.current_directory, chat_request.message
        )
        conversation_history = await _build_conversation_history(chat_session.id)

        async def event_generator():
            sources = []
            final_message = ""
            response_time = 0.0
            query_type = "document_search"
            retrieval_count = 0
            rerank_count = 0
            try:
                async for event_type, payload in state.doc_processor.query_stream(
                    chat_request.message, conversation_history=conversation_history
                ):
                    if event_type == "meta":
                        sources[:] = payload.get("sources", [])
                        query_type = payload.get("query_type", "document_search")
                        yield _format_sse("meta", {"sources": sources, "session_id": chat_session.id})
                    elif event_type == "token":
                        yield _format_sse("token", {"delta": payload})
                    elif event_type == "done":
                        final_message = payload.get("message", "")
                        response_time = payload.get("response_time", 0)
                        query_type = payload.get("query_type", query_type)
                        retrieval_count = payload.get("retrieval_count", 0)
                        rerank_count = payload.get("rerank_count", 0)
                        yield _format_sse("done", payload)
                    elif event_type == "error":
                        yield _format_sse("error", payload)
                        return

                await db_service.add_chat_message(
                    session_id=chat_session.id,
                    user_message=chat_request.message,
                    ai_response=final_message,
                    sources=sources,
                    response_time=response_time,
                )
                await _link_sources_to_session(sources, chat_session.id)
                _record_metrics(
                    chat_request.message, query_type, response_time,
                    len(sources), retrieval_count, rerank_count, chat_session.id,
                )
            except Exception as e:
                logger.error(f"Stream failed: {e}")
                yield _format_sse("error", {"detail": str(e)})

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception as e:
        logger.error(f"Chat stream setup failed: {e}")
        raise HTTPException(status_code=500, detail="Stream failed")


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------

class UpdateTitleRequest(BaseModel):
    title: str

class CreateSessionRequest(BaseModel):
    title: str


@router.get("/chat-sessions")
async def get_chat_sessions(state=Depends(require_app_state)):
    try:
        sessions = await db_service.get_chat_sessions_by_directory(state.current_directory)
        return {"status": "success", "sessions": sessions}
    except Exception as e:
        logger.error(f"Failed to get chat sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get chat sessions: {str(e)}")


@router.delete("/chat-sessions/{session_id}")
async def delete_chat_session(session_id: int):
    try:
        success = await db_service.delete_chat_session(session_id)
        if success:
            return {"status": "success", "message": "Chat session deleted"}
        raise HTTPException(status_code=404, detail="Chat session not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete chat session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete chat session: {str(e)}")


@router.put("/chat-sessions/{session_id}/title")
async def update_chat_title(session_id: int, request: UpdateTitleRequest):
    try:
        success = await db_service.update_chat_session_title(session_id, request.title)
        if not success:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return await db_service.get_chat_session_by_id(session_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update chat title: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update title: {str(e)}")


@router.post("/chat-sessions")
async def create_chat_session(request: CreateSessionRequest, state=Depends(require_app_state)):
    try:
        session = await db_service.create_chat_session(
            directory_path=state.current_directory, title=request.title
        )
        return session
    except Exception as e:
        logger.error(f"Failed to create chat session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create chat session: {str(e)}")


@router.get("/chat-sessions/{session_id}/messages")
async def get_chat_messages(session_id: int):
    from utils import utc_isoformat
    try:
        messages = await db_service.get_chat_history(session_id)
        return {
            "status": "success",
            "session_id": session_id,
            "messages": [
                {
                    "id": msg.id,
                    "user_message": msg.user_message,
                    "ai_response": msg.ai_response,
                    "sources": msg.sources,
                    "response_time": msg.response_time,
                    "timestamp": utc_isoformat(msg.timestamp),
                }
                for msg in messages
            ],
        }
    except Exception as e:
        logger.error(f"Failed to get chat messages: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get chat messages: {str(e)}")
