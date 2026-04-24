"""Chat and chat-session endpoints."""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import logging
import json
import re

from schemas.chat import ChatRequest, ChatResponse
from dependencies import db_service, require_app_state
from services.query_rewriter import rewrite_with_last_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _message_to_title(message: str, max_length: int = 48) -> str:
    """Build a short conversation title from the first user message."""
    if not message or not isinstance(message, str):
        return "New chat"
    trimmed = message.strip()
    if not trimmed:
        return "New chat"
    # Split on period or newline only so questions keep "?" and "!"
    first = re.split(r"[.\n]", trimmed, maxsplit=1)[0].strip()
    base = first or trimmed
    if len(base) <= max_length:
        return base
    return base[:max_length].rstrip() + "…"


async def _get_or_create_session(session_id: int | None, directory: str, message: str):
    """Resolve an existing session or create a new one."""
    title = _message_to_title(message)
    if session_id:
        try:
            session = await db_service.get_chat_session_by_id(session_id)
            if session:
                return session
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {e}")
    return await db_service.create_chat_session(directory_path=directory, title=title)


async def _build_conversation_history(session_id: int, doc_processor) -> list:
    try:
        previous = await db_service.get_chat_history(session_id)
        # Build ordered list of user/assistant pairs for the entire conversation
        pairs = [
            {"user": msg.user_message, "assistant": msg.ai_response}
            for msg in previous
        ]

        # Prefer orchestrator's summarization-aware history builder when available
        if hasattr(doc_processor, "build_conversation_history"):
            return await doc_processor.build_conversation_history(pairs, session_id=session_id)

        # Fallback: keep last 3 exchanges (previous behavior)
        recent = pairs[-3:] if len(pairs) > 3 else pairs
        history: list = []
        for pair in recent:
            user_msg = (pair.get("user") or "").strip()
            ai_msg = (pair.get("assistant") or "").strip()
            if user_msg:
                history.append({"role": "user", "content": user_msg})
            if ai_msg:
                history.append({"role": "assistant", "content": ai_msg})
        return history
    except Exception as e:
        logger.warning(f"Could not fetch conversation history: {e}")
        return []


async def _rewrite_query_for_session(session_id: int, raw_message: str) -> str:
    """
    Phase B.1 – Design A rewriting: pre-process the user query before retrieval.
    Uses the most recent chat message's sources (if any) to resolve pronouns like
    "that/this document/file" or "it" into the last document's filename.
    """
    try:
        last_msg = await db_service.get_last_chat_message_with_sources(session_id)
        last_sources = last_msg.sources if last_msg and last_msg.sources else None
        return rewrite_with_last_document(raw_message, last_sources)
    except Exception as e:
        logger.warning(f"Query rewrite skipped due to error: {e}")
        return raw_message


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@router.get("/chat/suggestions")
async def get_chat_suggestions(state=Depends(require_app_state)):
    """Return 4 context-aware suggested questions based on the indexed documents."""
    try:
        suggestions = await state.doc_processor.generate_suggestions()
        return {"suggestions": suggestions}
    except Exception as e:
        logger.warning("Failed to generate suggestions: %s", e)
        return {"suggestions": []}


@router.post("/chat", response_model=ChatResponse)
async def chat(chat_request: ChatRequest, request: Request, state=Depends(require_app_state)):
    """Query the document index with natural language."""
    try:
        chat_session = await _get_or_create_session(
            chat_request.session_id, state.current_directory, chat_request.message
        )

        # Phase B.1: rewrite query using last referenced document (if any)
        rewritten_message = await _rewrite_query_for_session(chat_session.id, chat_request.message)

        conversation_history = await _build_conversation_history(chat_session.id, state.doc_processor)
        response = await state.doc_processor.query(
            rewritten_message, conversation_history=conversation_history
        )

        await db_service.add_chat_message(
            session_id=chat_session.id,
            user_message=chat_request.message,
            ai_response=response.message,
            sources=response.sources,
            response_time=response.response_time,
        )
        await db_service.link_sources_to_chat(response.sources, chat_session.id)
        return ChatResponse(message=response.message, sources=response.sources)

    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(chat_request: ChatRequest, request: Request, state=Depends(require_app_state)):
    """Stream chat response as Server-Sent Events (meta -> token*N -> done)."""
    try:
        chat_session = await _get_or_create_session(
            chat_request.session_id, state.current_directory, chat_request.message
        )
        conversation_history = await _build_conversation_history(chat_session.id, state.doc_processor)
        rewritten_message = await _rewrite_query_for_session(chat_session.id, chat_request.message)

        async def event_generator():
            import asyncio as _asyncio
            sources = []
            final_message = ""
            response_time = 0.0
            query_type = "document_search"
            HEARTBEAT_INTERVAL = 15  # seconds between keepalive pings

            # Save the user turn to DB immediately so that conversation history
            # is consistent if a follow-up query arrives before the stream ends.
            try:
                pending_msg = await db_service.add_chat_message(
                    session_id=chat_session.id,
                    user_message=chat_request.message,
                    ai_response="",
                    sources=[],
                    response_time=0.0,
                )
                pending_msg_id: int | None = pending_msg.id
            except Exception as e:
                logger.error(f"Failed to pre-save chat message: {e}")
                pending_msg_id = None

            # Use a queue so the pipeline runs concurrently and we can emit
            # SSE keepalive comments whenever it goes quiet for >15 s.
            queue: _asyncio.Queue = _asyncio.Queue()

            async def _run_pipeline():
                try:
                    async for event_type, payload in state.doc_processor.query_stream(
                        rewritten_message, conversation_history=conversation_history
                    ):
                        await queue.put((event_type, payload))
                except Exception as exc:
                    await queue.put(("error", {"detail": str(exc)}))
                finally:
                    await queue.put(None)  # sentinel — stream finished

            pipeline_task = _asyncio.create_task(_run_pipeline())
            try:
                while True:
                    try:
                        item = await _asyncio.wait_for(
                            queue.get(), timeout=HEARTBEAT_INTERVAL
                        )
                    except _asyncio.TimeoutError:
                        # Proxy keepalive: SSE comment lines are ignored by browsers
                        # but prevent reverse-proxy idle timeouts (nginx, Apache).
                        yield ": keepalive\n\n"
                        continue

                    if item is None:
                        break  # pipeline finished

                    event_type, payload = item
                    if event_type == "meta":
                        sources[:] = payload.get("sources", [])
                        query_type = payload.get("query_type", "document_search")
                        yield _format_sse("meta", {"sources": sources, "session_id": chat_session.id})
                    elif event_type == "edit_proposal":
                        yield _format_sse("edit_proposal", payload)
                    elif event_type == "token":
                        yield _format_sse("token", {"delta": payload})
                    elif event_type == "done":
                        final_message = payload.get("message", "")
                        response_time = payload.get("response_time", 0)
                        query_type = payload.get("query_type", query_type)
                        yield _format_sse("done", payload)
                    elif event_type == "error":
                        yield _format_sse("error", payload)
            finally:
                pipeline_task.cancel()
                try:
                    await pipeline_task
                except (_asyncio.CancelledError, Exception):
                    pass

            # Update the pre-saved message with the final response.
            if pending_msg_id is not None and final_message:
                try:
                    await db_service.update_chat_message(
                        message_id=pending_msg_id,
                        ai_response=final_message,
                        sources=sources,
                        response_time=response_time,
                    )
                    await db_service.link_sources_to_chat(sources, chat_session.id)
                except Exception as e:
                    logger.error(f"Failed to update chat message {pending_msg_id}: {e}")

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
