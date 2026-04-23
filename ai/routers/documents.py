"""Document management, directory setup, PPTX preview, and update-queue endpoints."""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import FileResponse, Response, StreamingResponse
from typing import Optional
import asyncio
import logging
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from dependencies import db_service, require_app_state, validate_file_under_directory
from services.document_processor import DocumentProcessorOrchestrator
from services.file_monitor import FileMonitorService
from config import settings
from utils import utc_isoformat

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["documents"])


# ---------------------------------------------------------------------------
# Directory & index management
# ---------------------------------------------------------------------------

@router.post("/set-directory")
async def set_directory(request: Request):
    """Set the directory to process documents from."""
    body = await request.json()
    directory_path = body.get("path")
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path required")

    directory_path = os.path.normpath(os.path.abspath(directory_path))

    try:
        current_dir = getattr(request.app.state, "current_directory", None)
        if current_dir:
            if os.path.normpath(os.path.abspath(current_dir)).lower() == directory_path.lower():
                # Only skip if the DB still has indexed docs for this directory.
                # After /clear-index the app state may still point at the same directory,
                # but the index is empty and we must rebuild it.
                if await db_service.has_indexed_documents_for_directory(directory_path):
                    logger.info("Directory already set, skipping re-initialization")
                    return {
                        "status": "success",
                        "message": "Directory is already set. No re-initialization needed.",
                        "directory": directory_path,
                        "processing_status": "already_initialized",
                    }
                logger.info("Directory unchanged but index empty; re-initializing")

        old_monitor = getattr(request.app.state, "file_monitor", None)
        if old_monitor:
            await old_monitor.stop_monitoring()
        old_processor = getattr(request.app.state, "doc_processor", None)
        if old_processor:
            await old_processor.cancel_background_work()

        # Detect a restart / same-directory scenario: the app has no current_directory
        # (fresh start) but the DB already holds fully-indexed documents for this path.
        # In that case we skip clear_all_data() so the persisted BM25 pickle is reused
        # and only new/changed files are re-processed.
        is_resume = (
            current_dir is None
            and await db_service.has_indexed_documents_for_directory(directory_path)
        )

        doc_processor = DocumentProcessorOrchestrator(
            persist_dir=settings.CHROMA_PERSIST_DIR,
            embed_model_name=settings.EMBED_MODEL_NAME,
            max_file_size_mb=settings.MAX_FILE_SIZE_MB,
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            max_chunk_tokens=settings.MAX_CHUNK_TOKENS,
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            groq_model=settings.GROQ_MODEL,
            llm_provider=settings.LLM_PROVIDER,
            database_service=db_service,
            embedding_service=getattr(request.app.state, "embedding_service", None),
        )

        if is_resume:
            logger.info(
                f"Resuming previously-indexed directory: {directory_path} "
                "(skipping clear — reusing persisted BM25 and ChromaDB data)"
            )
        else:
            logger.info(f"Initializing document processor for directory: {directory_path}")
            await doc_processor.clear_all_data()

        # Start background tasks now that the DB is in its correct state.
        # Calling initialize() here (rather than in __init__) guarantees we are
        # inside an async context and that _load_existing_metadata reads the DB
        # *after* any clear_all_data() call has committed.
        await doc_processor.initialize()

        file_monitor = FileMonitorService(doc_processor)
        init_timeout = settings.INITIALIZE_DIRECTORY_TIMEOUT
        try:
            await asyncio.wait_for(
                doc_processor.initialize_from_directory(directory_path, resume_mode=is_resume),
                timeout=init_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Directory initialization timed out after {init_timeout}s for {directory_path}")
            raise HTTPException(
                status_code=504,
                detail=(
                    f"Directory initialization timed out after {init_timeout} seconds. "
                    "Try a smaller directory or increase INITIALIZE_DIRECTORY_TIMEOUT."
                ),
            )
        await file_monitor.start_monitoring(directory_path)

        request.app.state.doc_processor = doc_processor
        request.app.state.file_monitor = file_monitor
        request.app.state.current_directory = directory_path

        processing_status = "resumed" if is_resume else "background_processing"
        message = (
            "Directory resumed. Only new or changed files are being re-processed."
            if is_resume
            else "Directory set successfully. Documents are being processed in the background."
        )
        return {
            "status": "success",
            "message": message,
            "directory": directory_path,
            "processing_status": processing_status,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set directory {directory_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set directory: {str(e)}")


@router.post("/clear-index")
async def clear_index(state=Depends(require_app_state)):
    """Clear the entire index and database records."""
    try:
        await state.doc_processor.clear_all_data()
        logger.info("Document index and database records cleared successfully")
        return {"status": "success", "message": "Index and database records cleared"}
    except Exception as e:
        logger.error(f"Failed to clear index: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear index: {str(e)}")


@router.post("/reload-embedding-model")
async def reload_embedding_model(request: dict, state=Depends(require_app_state)):
    """Reload the embedding model with new configuration."""
    try:
        new_model = request.get("model_name")
        if not new_model:
            raise HTTPException(status_code=400, detail="Model name required")
        state.doc_processor.embedding_service.reload_model(new_model)
        logger.info(f"Embedding model reloaded to: {new_model}")
        return {"status": "success", "message": f"Model reloaded to {new_model}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reload embedding model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reload model: {str(e)}")


# ---------------------------------------------------------------------------
# Document queries
# ---------------------------------------------------------------------------

@router.get("/indexing/progress")
async def get_indexing_progress(request: Request):
    """Return real-time background content-indexing progress."""
    doc_processor = getattr(request.app.state, "doc_processor", None)
    if doc_processor is None:
        return {"status": "success", "progress": {"total": 0, "processed": 0, "failed": 0, "is_active": False}}
    try:
        progress = doc_processor.get_indexing_progress()
        return {"status": "success", "progress": progress}
    except Exception as e:
        logger.error(f"Failed to get indexing progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/stats")
async def get_document_stats():
    try:
        stats = await db_service.get_document_stats()
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error(f"Failed to get document stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get document stats: {str(e)}")


@router.get("/documents/search")
async def search_documents(
    query: str = "", file_type: str = "", date_from: str = "",
    date_to: str = "", limit: int = 50, offset: int = 0,
):
    try:
        documents = await db_service.search_documents(
            query=query, file_type=file_type, date_from=date_from,
            date_to=date_to, limit=limit, offset=offset,
        )
        return {"status": "success", "documents": documents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/autocomplete")
async def autocomplete_filenames(q: str = "", limit: int = 10, state=Depends(require_app_state)):
    if not q or len(q.strip()) < 1:
        return {"status": "success", "suggestions": []}
    try:
        suggestions = state.doc_processor.filename_trie.autocomplete(q.strip(), max_suggestions=limit)
        return {"status": "success", "query": q, "suggestions": suggestions, "count": len(suggestions)}
    except Exception as e:
        logger.error(f"Autocomplete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{document_id}")
async def get_document_metadata(document_id: int):
    try:
        document = await db_service.get_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found")
        return {
            "status": "success",
            "document": {
                "id": document.id,
                "file_path": document.file_path,
                "file_type": document.file_type,
                "file_size": document.file_size,
                "last_modified": utc_isoformat(document.last_modified),
                "content_preview": document.content_preview,
                "chunks_count": document.chunks_count,
                "processing_status": document.processing_status,
                "indexed_at": utc_isoformat(document.indexed_at),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document metadata {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get document metadata: {str(e)}")


@router.get("/documents/{document_id}/file")
async def get_document_file(request: Request, document_id: int, state=Depends(require_app_state)):
    """Serve a document file by its database ID."""
    try:
        document = await db_service.get_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found")

        file_path = document.file_path
        file_type = document.file_type.lower()
        path_obj = Path(file_path)
        if not path_obj.exists() or not path_obj.is_file():
            raise HTTPException(status_code=404, detail=f"Document file not found on disk: {path_obj.name}")
        validate_file_under_directory(path_obj, state.current_directory)

        actual_ext = path_obj.suffix.lower().lstrip(".")
        if actual_ext != file_type.lower().lstrip("."):
            raise HTTPException(status_code=400, detail="File extension does not match document record.")

        content_type_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        content_type = content_type_map.get(file_type, "application/octet-stream")

        if file_type == "txt":
            MAX_TEXT_DISPLAY = 10 * 1024 * 1024
            if path_obj.stat().st_size > MAX_TEXT_DISPLAY:
                raise HTTPException(status_code=413, detail="File too large to display.")
            for enc in ("utf-8", "latin-1"):
                try:
                    content = path_obj.read_text(encoding=enc)
                    return Response(
                        content=content, media_type=content_type,
                        headers={
                            "Content-Disposition": f'inline; filename="{path_obj.name}"',
                            "X-Document-Id": str(document_id), "X-File-Type": file_type,
                        },
                    )
                except UnicodeDecodeError:
                    continue
            raise HTTPException(status_code=500, detail="Failed to decode text file")

        return FileResponse(
            path=file_path, media_type=content_type, filename=path_obj.name,
            headers={
                "X-Document-Id": str(document_id), "X-File-Type": file_type,
                "X-File-Size": str(document.file_size) if document.file_size else "0",
                "Cache-Control": "no-store",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve document file {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to serve document file: {str(e)}")


@router.get("/documents/{document_id}/preview")
async def get_document_preview(
    request: Request, document_id: int,
    format: str = "pdf", force_refresh: bool = False,
    state=Depends(require_app_state),
):
    """Get a preview of a document (currently PPTX -> PDF)."""
    pptx_converter = getattr(request.app.state, "pptx_converter", None)
    if not pptx_converter or not pptx_converter.is_available():
        raise HTTPException(status_code=503, detail="PPTX preview service not available.")

    try:
        document = await db_service.get_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found")

        file_type = document.file_type.lower().replace(".", "")
        path_obj = Path(document.file_path)
        if not path_obj.exists() or not path_obj.is_file():
            raise HTTPException(status_code=404, detail=f"Document file not found on disk: {path_obj.name}")
        validate_file_under_directory(path_obj, state.current_directory)

        if path_obj.suffix.lower().lstrip(".") != file_type.lstrip("."):
            raise HTTPException(status_code=400, detail="File extension does not match document record.")
        if file_type != "pptx":
            raise HTTPException(status_code=400, detail=f"Preview not supported for file type: {file_type}.")
        if format != "pdf":
            raise HTTPException(status_code=400, detail=f"Preview format '{format}' not supported.")

        use_cache = settings.PPTX_CACHE_ENABLED and not force_refresh
        timeout = settings.PPTX_CONVERSION_TIMEOUT
        try:
            pdf_path = await asyncio.wait_for(
                pptx_converter.convert_pptx_to_pdf(document.file_path, use_cache=use_cache),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail=f"Preview conversion timed out after {timeout} seconds.")

        return FileResponse(
            path=pdf_path, media_type="application/pdf", filename=f"{path_obj.stem}.pdf",
            headers={
                "X-Document-Id": str(document_id), "X-Original-File": path_obj.name,
                "X-Preview-Format": "pdf",
                "X-Cache-Used": "true" if use_cache and pptx_converter.get_cached_pdf(document.file_path) else "false",
                "Cache-Control": "no-store",
            },
        )
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"PPTX file not found: {str(e)}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to convert PPTX to PDF: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to generate preview for document {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {str(e)}")


# ---------------------------------------------------------------------------
# PPTX cache
# ---------------------------------------------------------------------------

@router.get("/pptx-cache/stats")
async def get_pptx_cache_stats(request: Request):
    pptx_converter = getattr(request.app.state, "pptx_converter", None)
    if not pptx_converter:
        raise HTTPException(status_code=503, detail="PPTX preview service not available.")
    try:
        return {"status": "success", "cache_stats": pptx_converter.get_cache_stats()}
    except Exception as e:
        logger.error(f"Failed to get PPTX cache stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get cache stats: {str(e)}")


@router.delete("/pptx-cache/clear")
async def clear_pptx_cache(request: Request, older_than_days: Optional[int] = None):
    pptx_converter = getattr(request.app.state, "pptx_converter", None)
    if not pptx_converter:
        raise HTTPException(status_code=503, detail="PPTX preview service not available.")
    try:
        result = pptx_converter.clear_cache(older_than_days=older_than_days)
        return {
            "status": "success",
            "message": f"Cleared {result['cleared_count']} cache files ({result['total_size_mb']} MB)",
            "cache_cleared": result,
        }
    except Exception as e:
        logger.error(f"Failed to clear PPTX cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


# ---------------------------------------------------------------------------
# Update queue
# ---------------------------------------------------------------------------

@router.get("/updates/queue")
async def get_update_queue_status(state=Depends(require_app_state)):
    if not hasattr(state.doc_processor, "update_queue"):
        raise HTTPException(status_code=400, detail="Update queue not available")
    try:
        status = state.doc_processor.update_queue.get_status()
        pending_tasks = state.doc_processor.update_queue.get_pending_tasks(limit=10)
        return {
            "status": "success",
            "queue": {
                "pending": status["pending"], "processing": status["processing"],
                "completed": status["completed"], "failed": status["failed"],
                "pending_tasks": pending_tasks,
            },
        }
    except Exception as e:
        logger.error(f"Failed to get update queue status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get update queue status: {str(e)}")


@router.get("/updates/status/{file_path:path}")
async def get_update_status(file_path: str, state=Depends(require_app_state)):
    if not hasattr(state.doc_processor, "update_queue"):
        raise HTTPException(status_code=400, detail="Update queue not available")
    try:
        active_file = None
        if file_path in state.doc_processor.update_queue.active_updates:
            task = state.doc_processor.update_queue.active_updates[file_path]
            active_file = {
                "file_path": task.file_path, "priority": task.priority,
                "update_type": task.update_type,
                "enqueued_at": task.enqueued_at.isoformat(),
            }
        completed_result = None
        if file_path in state.doc_processor.update_queue.completed_updates:
            r = state.doc_processor.update_queue.completed_updates[file_path]
            completed_result = {
                "success": r.success, "chunks_updated": r.chunks_updated,
                "processing_time": r.processing_time,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "error_message": r.error_message,
            }
        return {"status": "success", "file_path": file_path, "active": active_file, "completed": completed_result}
    except Exception as e:
        logger.error(f"Failed to get update status for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get update status: {str(e)}")


@router.post("/updates/force")
async def force_update(request: dict, state=Depends(require_app_state)):
    if not hasattr(state.doc_processor, "enqueue_update"):
        raise HTTPException(status_code=400, detail="Update queue not available")
    file_path = request.get("file_path")
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path required")
    try:
        success = await state.doc_processor.enqueue_update(
            file_path=file_path, update_type="modified", user_requested=True,
        )
        if success:
            return {"status": "success", "message": f"Update enqueued for {file_path} with high priority"}
        raise HTTPException(status_code=500, detail="Failed to enqueue update (queue may be full)")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to force update {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to force update: {str(e)}")


@router.get("/updates/stream")
async def stream_update_status(state=Depends(require_app_state)):
    """SSE stream for real-time update queue status."""
    if not hasattr(state.doc_processor, "update_queue"):
        raise HTTPException(status_code=400, detail="Update queue not available")

    async def event_generator():
        last_status = None
        try:
            while True:
                status = state.doc_processor.update_queue.get_status()
                current = {
                    "pending": status["pending"], "processing": status["processing"],
                    "completed": status["completed"], "failed": status["failed"],
                }
                if current != last_status:
                    yield f"data: {json.dumps({'status': 'success', 'queue': current, 'timestamp': utc_isoformat(datetime.now(timezone.utc))})}\n\n"
                    last_status = current
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in SSE stream: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
