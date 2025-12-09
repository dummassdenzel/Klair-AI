from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
import asyncio
import logging
import os
import json
from pathlib import Path
from services.document_processor import DocumentProcessorOrchestrator, config
from services.document_processor.extraction import PPTXConverter
from config import settings
from services.file_monitor import FileMonitorService
from schemas.chat import ChatRequest, ChatResponse

# NEW: Add database imports
from database import DatabaseService, get_db
from database.models import ChatSession, ChatMessage, IndexedDocument
from datetime import datetime
from sqlalchemy import select, func, or_, and_, desc

# Configure structured logging
from services.logging_config import setup_logging, log_query_metrics, MetricsLogger
from services.metrics_service import MetricsService
from services.rag_analytics import RAGAnalytics

setup_logging(
    json_format=(settings.LOG_FORMAT.lower() == "json"),
    log_level=settings.LOG_LEVEL,
    log_file=settings.LOG_FILE if settings.LOG_FILE else None
)

logger = logging.getLogger(__name__)

# Global state
doc_processor: Optional[DocumentProcessorOrchestrator] = None
file_monitor: Optional[FileMonitorService] = None
current_directory: Optional[str] = None
metrics_service = MetricsService(max_history=1000)  # Store last 1000 queries
rag_analytics = RAGAnalytics(metrics_service)
prewarming_complete = False
prewarming_task = None
 
# NEW: Add database service
db_service = DatabaseService()

# PPTX Converter for preview functionality
pptx_converter: Optional[PPTXConverter] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global prewarming_complete, prewarming_task
    
    # Startup
    logger.info("Starting AI Document Assistant...")
    
    # Initialize PPTX converter
    global pptx_converter
    libreoffice_path = settings.LIBREOFFICE_PATH if settings.LIBREOFFICE_PATH else None
    pptx_converter = PPTXConverter(
        libreoffice_path=libreoffice_path,
        cache_dir=settings.PPTX_CACHE_DIR
    )
    if pptx_converter.is_available():
        logger.info("PPTX preview functionality enabled")
    else:
        logger.warning("PPTX preview disabled: LibreOffice not found")
    
    # Start pre-warming immediately
    prewarming_task = asyncio.create_task(prewarm_services())
    
    yield
    
    # Shutdown
    logger.info("Shutting down AI Document Assistant...")
    global file_monitor, doc_processor
    if file_monitor:
        await file_monitor.stop_monitoring()
    if doc_processor:
        await doc_processor.cleanup()
    
    # Cancel pre-warming if still running
    if prewarming_task and not prewarming_task.done():
        prewarming_task.cancel()

async def prewarm_services():
    """Pre-warm services to avoid cold start delays"""
    global prewarming_complete
    
    try:
        logger.info("Pre-warming services...")
        
        # Pre-warm embedding service with a minimal processor
        from services.document_processor import DocumentProcessorOrchestrator
        temp_processor = DocumentProcessorOrchestrator(
            persist_dir="./temp_chroma_db",
            embed_model_name=config.embed_model_name,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            ollama_base_url=config.ollama_base_url,
            ollama_model=config.ollama_model,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            llm_provider=settings.LLM_PROVIDER
        )
        
        # Warm up embedding model (this is the biggest time saver)
        logger.info("Warming up embedding model...")
        test_texts = [
            "This is a test document for warming up the embedding model.",
            "Another test to ensure the model is fully loaded.",
            "Final test to warm up the embedding service completely."
        ]
        _ = temp_processor.embedding_service.encode_texts(test_texts)
        logger.info("Embedding model warmed up")
        
        # Warm up LLM service with a simple test
        logger.info("Warming up LLM service...")
        test_response = await temp_processor.llm_service.generate_response(
            "Hello", "This is a test context for warming up the LLM service."
        )
        logger.info("LLM service warmed up")
        
        # Cleanup temp processor
        await temp_processor.cleanup()
        
        prewarming_complete = True
        logger.info("Service pre-warming completed successfully!")
        
    except Exception as e:
        logger.warning(f"Service pre-warming failed (this is okay): {e}")
        # Don't fail startup if pre-warming fails

app = FastAPI(
    title="AI Document Assistant",
    description="RAG-powered document chat assistant with modular architecture",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "tauri://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/select-directory")
async def select_directory():
    """
    Open a native directory picker dialog on the server.
    Returns the selected directory path and file count.
    Runs in a thread to avoid blocking the async event loop.
    """
    def _open_picker():
        """Open directory picker in a separate thread"""
        try:
            import tkinter as tk
            from tkinter import filedialog
            from pathlib import Path
            
            # Create a root window (hidden)
            root = tk.Tk()
            root.withdraw()  # Hide the main window
            root.attributes('-topmost', True)  # Bring to front
            
            # Open directory picker
            directory_path = filedialog.askdirectory(
                title="Select Documents Directory",
                mustexist=True
            )
            
            root.destroy()
            
            if not directory_path:
                return None, 0
            
            # Count supported files in the directory
            dir_path = Path(directory_path)
            supported_extensions = {'.pdf', '.docx', '.txt', '.xlsx', '.xls', '.pptx'}
            file_count = 0
            
            if dir_path.exists() and dir_path.is_dir():
                for file_path in dir_path.rglob('*'):
                    if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                        file_count += 1
            
            return directory_path, file_count
            
        except ImportError:
            return None, 0
        except Exception as e:
            logger.error(f"Directory picker error: {e}")
            return None, 0
    
    try:
        # Run in thread to avoid blocking async event loop
        directory_path, file_count = await asyncio.to_thread(_open_picker)
        
        if not directory_path:
            # User cancelled or tkinter not available
            raise HTTPException(
                status_code=400,
                detail="No directory selected or directory picker not available"
            )
        
        return {
            "status": "success",
            "directory_path": directory_path,
            "file_count": file_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to open directory picker: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open directory picker: {str(e)}")

@app.post("/api/set-directory")
async def set_directory(request: dict):
    """Set the directory to monitor and process documents from"""
    import os
    global doc_processor, file_monitor, current_directory
    
    directory_path = request.get("path")
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path required")
    
    # Normalize directory path for consistent storage and comparison
    directory_path = os.path.normpath(os.path.abspath(directory_path))
    
    try:
        # Normalize both paths for comparison (case-insensitive on Windows)
        normalized_new_path = os.path.normpath(os.path.abspath(directory_path))
        normalized_current_path = os.path.normpath(os.path.abspath(current_directory)) if current_directory else None
        
        # Check if it's the same directory - if so, skip re-initialization
        if normalized_current_path and normalized_current_path.lower() == normalized_new_path.lower():
            logger.info(f"Directory {directory_path} is already set, skipping re-initialization")
            return {
                "status": "success",
                "message": "Directory is already set. No re-initialization needed.",
                "directory": directory_path,
                "processing_status": "already_initialized"
            }
        
        # Stop existing file monitor
        if file_monitor:
            await file_monitor.stop_monitoring()
        
        # Initialize document processor with configuration
        doc_processor = DocumentProcessorOrchestrator(
            persist_dir=config.persist_dir,
            embed_model_name=config.embed_model_name,
            max_file_size_mb=config.max_file_size_mb,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            ollama_base_url=config.ollama_base_url,
            ollama_model=config.ollama_model,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            llm_provider=settings.LLM_PROVIDER
        )
        
        logger.info(f"Initializing document processor for directory: {directory_path}")
        
        # Clear old directory data synchronously (prevents race conditions)
        logger.info("Clearing previous directory data...")
        await doc_processor.clear_all_data()
        logger.info("Previous directory data cleared successfully")
        
        current_directory = directory_path
        
        # Process existing documents first (before starting file monitor to avoid duplicate events)
        # Wait for metadata indexing to complete before starting file monitor
        logger.info("Starting initial directory indexing...")
        await doc_processor.initialize_from_directory(directory_path)
        logger.info("Initial directory indexing complete, starting file monitor...")
        
        # Start file monitoring after initial indexing is complete
        file_monitor = FileMonitorService(doc_processor)
        await file_monitor.start_monitoring(directory_path)
        
        return {
            "status": "success",
            "message": "Directory set successfully. Documents are being processed in the background.",
            "directory": directory_path,
            "processing_status": "background_processing"
        }
        
    except Exception as e:
        logger.error(f"Failed to set directory {directory_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set directory: {str(e)}")

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Query the document index with natural language"""
    if not doc_processor:
        raise HTTPException(status_code=400, detail="No directory set")
    
    try:
        logger.info(f"Processing chat query: {request.message[:100]}...")
        
        # FIX: Check if session_id exists, create new only if needed
        if request.session_id:
            # Try to get existing session
            try:
                chat_session = await db_service.get_chat_session_by_id(request.session_id)
                if chat_session:
                    logger.info(f"Using existing session: {request.session_id}")
                else:
                    logger.warning(f"Session {request.session_id} not found, creating new one")
                    chat_session = await db_service.create_chat_session(
                        directory_path=current_directory,
                        title=f"Chat about: {request.message[:50]}..."
                    )
            except Exception as e:
                logger.error(f"Error getting session {request.session_id}: {e}")
                # Fallback to creating new session
                chat_session = await db_service.create_chat_session(
                    directory_path=current_directory,
                    title=f"Chat about: {request.message[:50]}..."
                )
        else:
            # No session_id provided, create new session
            chat_session = await db_service.create_chat_session(
                directory_path=current_directory,
                title=f"Chat about: {request.message[:50]}..."
            )
        
        # Get conversation history for context (last 3 messages for efficiency)
        conversation_history = []
        try:
            previous_messages = await db_service.get_chat_history(chat_session.id)
            # Get last 3 messages for context (balance between context and speed)
            recent_messages = previous_messages[-3:] if len(previous_messages) > 3 else previous_messages
            
            # Interleave user and assistant messages properly
            conversation_history = []
            for msg in recent_messages:
                conversation_history.append({"role": "user", "content": msg.user_message})
                conversation_history.append({"role": "assistant", "content": msg.ai_response})
            
            logger.info(f"Including {len(recent_messages)} previous messages in conversation context")
        except Exception as e:
            logger.warning(f"Could not fetch conversation history: {e}")
            conversation_history = []
        
        # Query RAG system with conversation context
        response = await doc_processor.query(request.message, conversation_history=conversation_history)
        
        # Store chat message in database
        await db_service.add_chat_message(
            session_id=chat_session.id,
            user_message=request.message,
            ai_response=response.message,
            sources=response.sources,
            response_time=response.response_time
        )
        
        # Link documents used in this chat (FIXED: Use existing document records)
        for source in response.sources:
            file_path = source.get("file_path")
            if file_path:
                try:
                    # Get existing document record from database
                    async for db_session in get_db():
                        stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
                        result = await db_session.execute(stmt)
                        existing_doc = result.scalar_one_or_none()
                        
                        if existing_doc:
                            # Document already exists with complete metadata - just link it
                            await db_service.link_document_to_chat(
                                document_id=existing_doc.id,
                                chat_session_id=chat_session.id
                            )
                            logger.debug(f"Linked existing document {file_path} to chat session {chat_session.id}")
                        else:
                            # Document doesn't exist in database (shouldn't happen, but handle gracefully)
                            logger.warning(f"Document {file_path} not found in database during chat linking")
                            # Create minimal record for linking (fallback)
                            doc = await db_service.store_document_metadata(
                                file_path=file_path,
                                file_hash="",  # Will be updated when file is processed
                                file_type=source.get("file_type", "unknown"),
                                file_size=0,  # Will be updated when file is processed
                                last_modified=datetime.utcnow(),  # Will be updated when file is processed
                                content_preview=source.get("content_snippet", "")[:500],
                                chunks_count=source.get("chunks_found", 0)
                            )
                            await db_service.link_document_to_chat(
                                document_id=doc.id,
                                chat_session_id=chat_session.id
                            )
                            logger.info(f"Created fallback document record for {file_path}")
                
                except Exception as e:
                    logger.error(f"Error linking document {file_path} to chat: {e}")
                    # Continue with other documents - don't fail the entire chat
        
        # Log structured query metrics
        query_type = response.query_type or "unknown"
        log_query_metrics(
            logger=logger,
            query=request.message,
            query_type=query_type,
            response_time=response.response_time,
            sources_count=len(response.sources),
            retrieval_count=response.retrieval_count,
            rerank_count=response.rerank_count,
            session_id=chat_session.id
        )
        
        # Record metrics for dashboard
        metrics_service.record_query(
            query_type=query_type,
            response_time_ms=response.response_time * 1000,  # Convert to ms
            sources_count=len(response.sources),
            retrieval_count=response.retrieval_count or 0,
            rerank_count=response.rerank_count or 0,
            session_id=chat_session.id,
            query_preview=request.message[:100]  # First 100 chars
        )
        
        return ChatResponse(
            message=response.message,
            sources=response.sources
        )
        
    except Exception as e:
        logger.error(f"Query failed: {e}")
        
        # Record error metric
        metrics_service.record_query(
            query_type="error",
            response_time_ms=0,
            sources_count=0,
            retrieval_count=0,
            rerank_count=0,
            error=True,
            error_message=str(e)
        )
        
        raise HTTPException(status_code=500, detail="Query failed: {str(e)}")

@app.get("/api/status")
async def get_status():
    """Get current system status and configuration"""
    try:
        status_info = {
        "directory_set": current_directory is not None,
        "current_directory": current_directory,
            "processor_ready": doc_processor is not None and doc_processor.is_ready() if doc_processor else False,
        "monitor_running": file_monitor is not None and file_monitor.is_running if file_monitor else False,
        }
        
        # Add configuration info safely
        try:
            status_info["configuration"] = config.to_dict()
        except Exception as e:
            logger.warning(f"Could not get configuration: {e}")
            status_info["configuration"] = {"error": "Configuration not available"}
        
        # Add active LLM provider/model info
        try:
            provider = (settings.LLM_PROVIDER or "ollama").lower()
            if provider == "gemini":
                model_name = settings.GEMINI_MODEL or "gemini-2.5-pro"
            else:
                model_name = getattr(config, "ollama_model", "tinyllama")
            status_info["llm"] = {
                "provider": provider,
                "model": model_name
            }
        except Exception as e:
            logger.warning(f"Could not determine LLM provider/model: {e}")
        
        # Add index stats if processor is available
        if doc_processor:
            try:
                status_info["index_stats"] = doc_processor.get_stats()
            except Exception as e:
                logger.warning(f"Could not get index stats: {e}")
                status_info["index_stats"] = {"error": "Stats not available"}
        
        # NEW: Add database stats
        try:
            doc_stats = await db_service.get_document_stats()
            status_info["database_stats"] = doc_stats
        except Exception as e:
            logger.warning(f"Could not get database stats: {e}")
            status_info["database_stats"] = {"error": "Database stats not available"}
        
        return status_info
        
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return {"error": str(e)}

@app.get("/api/configuration")
async def get_configuration():
    """Get current configuration settings"""
    return {
        "current_config": config.to_dict(),
        "environment_variables": {
            "CHROMA_PERSIST_DIR": config.persist_dir,
            "EMBED_MODEL_NAME": config.embed_model_name,
            "MAX_FILE_SIZE_MB": config.max_file_size_mb,
            "CHUNK_SIZE": config.chunk_size,
            "CHUNK_OVERLAP": config.chunk_overlap,
            "OLLAMA_BASE_URL": config.ollama_base_url,
            "OLLAMA_MODEL": config.ollama_model
        }
    }

@app.post("/api/update-configuration")
async def update_configuration(request: dict):
    """Update configuration settings"""
    try:
        # Validate configuration updates
        allowed_updates = {
            'chunk_size', 'chunk_overlap', 'max_file_size_mb',
            'ollama_model', 'ollama_base_url'
        }
        
        updates = {k: v for k, v in request.items() if k in allowed_updates}
        
        if not updates:
            raise HTTPException(status_code=400, detail="No valid configuration updates provided")
        
        # Update configuration
        config.update(**updates)
        
        logger.info(f"Configuration updated: {updates}")
        
        return {
            "status": "success",
            "message": "Configuration updated",
            "updated_values": updates,
            "current_config": config.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Configuration update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Configuration update failed: {str(e)}")

@app.post("/api/clear-index")
async def clear_index():
    """Clear the entire index and database records"""
    global doc_processor
    if doc_processor:
        try:
            await doc_processor.clear_all_data()
            
            logger.info("Document index and database records cleared successfully")
            return {"status": "success", "message": "Index and database records cleared"}
            
        except Exception as e:
            logger.error(f"Failed to clear index: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to clear index: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="No processor initialized")

@app.post("/api/reload-embedding-model")
async def reload_embedding_model(request: dict):
    """Reload the embedding model with new configuration"""
    global doc_processor
    
    if not doc_processor:
        raise HTTPException(status_code=400, detail="No processor initialized")
    
    try:
        new_model = request.get("model_name")
        if not new_model:
            raise HTTPException(status_code=400, detail="Model name required")
        
        # Reload the embedding model
        doc_processor.embedding_service.reload_model(new_model)
        
        logger.info(f"Embedding model reloaded to: {new_model}")
        return {"status": "success", "message": f"Model reloaded to {new_model}"}
        
    except Exception as e:
        logger.error(f"Failed to reload embedding model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reload model: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global doc_processor, file_monitor
    logger.info("Shutting down services...")
    
    if file_monitor:
        await file_monitor.stop_monitoring()
    if doc_processor:
        await doc_processor.cleanup()
    
    logger.info("Shutdown complete")

@app.get("/api/chat-sessions")
async def get_chat_sessions():
    """Get all chat sessions for the current directory"""
    if not current_directory:
        raise HTTPException(status_code=400, detail="No directory set")
    
    try:
        sessions = await db_service.get_chat_sessions_by_directory(current_directory)
        return {"status": "success", "sessions": sessions}
    except Exception as e:
        logger.error(f"Failed to get chat sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get chat sessions: {str(e)}")

@app.delete("/api/chat-sessions/{session_id}")
async def delete_chat_session(session_id: int):
    """Delete a chat session and all its messages"""
    try:
        success = await db_service.delete_chat_session(session_id)
        if success:
            return {"status": "success", "message": "Chat session deleted"}
        else:
            raise HTTPException(status_code=404, detail="Chat session not found")
    except Exception as e:
        logger.error(f"Failed to delete chat session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete chat session: {str(e)}")

class UpdateTitleRequest(BaseModel):
    title: str

class CreateSessionRequest(BaseModel):
    title: str

@app.put("/api/chat-sessions/{session_id}/title")
async def update_chat_title(session_id: int, request: UpdateTitleRequest):
    """Update chat session title (expects JSON body { title }) and return updated session"""
    try:
        success = await db_service.update_chat_session_title(session_id, request.title)
        if not success:
            raise HTTPException(status_code=404, detail="Chat session not found")
        # Return updated session
        updated = await db_service.get_chat_session_by_id(session_id)
        return updated
    except Exception as e:
        logger.error(f"Failed to update chat title: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update title: {str(e)}")

@app.post("/api/chat-sessions")
async def create_chat_session(request: CreateSessionRequest):
    """Create a chat session for the current directory and return it"""
    if not current_directory:
        raise HTTPException(status_code=400, detail="No directory set")
    try:
        session = await db_service.create_chat_session(
            directory_path=current_directory,
            title=request.title
        )
        return session
    except Exception as e:
        logger.error(f"Failed to create chat session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create chat session: {str(e)}")

@app.get("/api/chat-sessions/{session_id}/messages")
async def get_chat_messages(session_id: int):
    """Get all messages for a specific chat session"""
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
                    "timestamp": msg.timestamp.isoformat()
                }
                for msg in messages
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get chat messages: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get chat messages: {str(e)}")

@app.get("/api/documents/stats")
async def get_document_stats():
    """Get statistics about indexed documents"""
    try:
        stats = await db_service.get_document_stats()
        return {
            "status": "success",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Failed to get document stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get document stats: {str(e)}")

# Metrics Dashboard API Endpoints
@app.get("/api/metrics/summary")
async def get_metrics_summary(time_window_minutes: int = 60):
    """Get aggregated metrics summary for a time window"""
    try:
        summary = metrics_service.get_metrics_summary(time_window_minutes=time_window_minutes)
        return {
            "status": "success",
            "metrics": summary
        }
    except Exception as e:
        logger.error(f"Failed to get metrics summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get metrics summary: {str(e)}")

@app.get("/api/metrics/retrieval-stats")
async def get_retrieval_stats(time_window_minutes: int = 60):
    """Get retrieval operation statistics"""
    try:
        stats = metrics_service.get_retrieval_stats(time_window_minutes=time_window_minutes)
        return {
            "status": "success",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Failed to get retrieval stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get retrieval stats: {str(e)}")

@app.get("/api/metrics/time-series")
async def get_time_series(
    metric_type: str = "response_time",
    time_window_minutes: int = 60,
    bucket_minutes: int = 5
):
    """Get time series data for a metric"""
    try:
        time_series = metrics_service.get_time_series(
            metric_type=metric_type,
            time_window_minutes=time_window_minutes,
            bucket_minutes=bucket_minutes
        )
        return {
            "status": "success",
            "metric_type": metric_type,
            "time_series": time_series
        }
    except Exception as e:
        logger.error(f"Failed to get time series: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get time series: {str(e)}")

@app.get("/api/metrics/recent-queries")
async def get_recent_queries(limit: int = 20):
    """Get recent query metrics"""
    try:
        queries = metrics_service.get_recent_queries(limit=limit)
        return {
            "status": "success",
            "queries": queries
        }
    except Exception as e:
        logger.error(f"Failed to get recent queries: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get recent queries: {str(e)}")

@app.get("/api/metrics/counters")
async def get_counters():
    """Get all counter metrics"""
    try:
        counters = metrics_service.get_counters()
        return {
            "status": "success",
            "counters": counters
        }
    except Exception as e:
        logger.error(f"Failed to get counters: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get counters: {str(e)}")

# RAG Analytics API Endpoints
@app.get("/api/analytics/query-patterns")
async def get_query_patterns(time_window_minutes: int = 60):
    """Get query pattern analytics"""
    try:
        patterns = rag_analytics.get_query_patterns(time_window_minutes=time_window_minutes)
        return {
            "status": "success",
            "patterns": patterns
        }
    except Exception as e:
        logger.error(f"Failed to get query patterns: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get query patterns: {str(e)}")

@app.get("/api/analytics/document-usage")
async def get_document_usage():
    """Get document usage statistics"""
    try:
        usage = rag_analytics.get_document_usage_stats()
        return {
            "status": "success",
            "usage": usage
        }
    except Exception as e:
        logger.error(f"Failed to get document usage: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get document usage: {str(e)}")

@app.get("/api/analytics/retrieval-effectiveness")
async def get_retrieval_effectiveness(time_window_minutes: int = 60):
    """Get retrieval effectiveness metrics"""
    try:
        effectiveness = rag_analytics.get_retrieval_effectiveness(time_window_minutes=time_window_minutes)
        return {
            "status": "success",
            "effectiveness": effectiveness
        }
    except Exception as e:
        logger.error(f"Failed to get retrieval effectiveness: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get retrieval effectiveness: {str(e)}")

@app.get("/api/analytics/performance-trends")
async def get_performance_trends(time_window_minutes: int = 60, buckets: int = 6):
    """Get performance trend analysis"""
    try:
        trends = rag_analytics.get_performance_trends(
            time_window_minutes=time_window_minutes,
            buckets=buckets
        )
        return {
            "status": "success",
            "trends": trends
        }
    except Exception as e:
        logger.error(f"Failed to get performance trends: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get performance trends: {str(e)}")

@app.get("/api/analytics/query-success")
async def get_query_success(time_window_minutes: int = 60):
    """Get query success analysis"""
    try:
        success = rag_analytics.get_query_success_analysis(time_window_minutes=time_window_minutes)
        return {
            "status": "success",
            "success": success
        }
    except Exception as e:
        logger.error(f"Failed to get query success: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get query success: {str(e)}")

@app.get("/api/documents/search")
async def search_documents(
    query: str = "",
    file_type: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
    offset: int = 0
):
    """Search documents with various filters"""
    try:
        documents = await db_service.search_documents(
            query=query,
            file_type=file_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset
        )
        return {"status": "success", "documents": documents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/autocomplete")
async def autocomplete_filenames(q: str = "", limit: int = 10):
    """
    Get autocomplete suggestions for filenames using Trie.
    Fast O(m) search where m = query length.
    """
    if not doc_processor:
        raise HTTPException(status_code=400, detail="No directory set")
    
    if not q or len(q.strip()) < 1:
        return {"status": "success", "suggestions": []}
    
    try:
        # Use Trie for instant autocomplete
        suggestions = doc_processor.filename_trie.autocomplete(q.strip(), max_suggestions=limit)
        
        return {
            "status": "success",
            "query": q,
            "suggestions": suggestions,
            "count": len(suggestions)
        }
    except Exception as e:
        logger.error(f"Autocomplete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/{document_id}/file")
async def get_document_file(document_id: int):
    """
    Serve a document file by its ID.
    Returns the file content with appropriate content-type headers.
    """
    try:
        # Get document from database
        async for db_session in get_db():
            stmt = select(IndexedDocument).where(IndexedDocument.id == document_id)
            result = await db_session.execute(stmt)
            document = result.scalar_one_or_none()
            
            if not document:
                raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found")
            
            file_path = document.file_path
            file_type = document.file_type.lower()
            
            # Validate file exists
            path_obj = Path(file_path)
            if not path_obj.exists() or not path_obj.is_file():
                logger.error(f"Document file not found on disk: {file_path}")
                raise HTTPException(
                    status_code=404, 
                    detail=f"Document file not found on disk: {path_obj.name}"
                )
            
            # Determine content type based on file extension
            content_type_map = {
                'pdf': 'application/pdf',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'txt': 'text/plain',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'xls': 'application/vnd.ms-excel',
                'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
            }
            
            content_type = content_type_map.get(file_type, 'application/octet-stream')
            
            # For TXT files, read and return as text response
            if file_type == 'txt':
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    return Response(
                        content=content,
                        media_type=content_type,
                        headers={
                            "Content-Disposition": f'inline; filename="{path_obj.name}"',
                            "X-Document-Id": str(document_id),
                            "X-File-Type": file_type
                        }
                    )
                except UnicodeDecodeError:
                    # Try with different encoding if UTF-8 fails
                    try:
                        with open(file_path, 'r', encoding='latin-1') as f:
                            content = f.read()
                        return Response(
                            content=content,
                            media_type=content_type,
                            headers={
                                "Content-Disposition": f'inline; filename="{path_obj.name}"',
                                "X-Document-Id": str(document_id),
                                "X-File-Type": file_type
                            }
                        )
                    except Exception as e:
                        logger.error(f"Failed to read TXT file {file_path}: {e}")
                        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")
            
            # For PDF, DOCX, and Excel files, return file response
            return FileResponse(
                path=file_path,
                media_type=content_type,
                filename=path_obj.name,
                headers={
                    "X-Document-Id": str(document_id),
                    "X-File-Type": file_type,
                    "X-File-Size": str(document.file_size) if document.file_size else "0"
                }
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve document file {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to serve document file: {str(e)}")

@app.get("/api/documents/{document_id}/preview")
async def get_document_preview(document_id: int, format: str = "pdf", force_refresh: bool = False):
    """
    Get a preview of a document in a viewable format.
    Currently supports PPTX -> PDF conversion for PowerPoint files.
    
    Args:
        document_id: ID of the document
        format: Requested preview format (default: "pdf")
        force_refresh: If True, bypass cache and regenerate preview
        
    Returns:
        Preview file (PDF for PPTX files)
    """
    global pptx_converter
    
    if not pptx_converter:
        raise HTTPException(
            status_code=503, 
            detail="PPTX preview service not available. LibreOffice may not be installed."
        )
    
    if not pptx_converter.is_available():
        raise HTTPException(
            status_code=503,
            detail="PPTX preview service not available. LibreOffice not found."
        )
    
    try:
        # Get document from database
        async for db_session in get_db():
            stmt = select(IndexedDocument).where(IndexedDocument.id == document_id)
            result = await db_session.execute(stmt)
            document = result.scalar_one_or_none()
            
            if not document:
                raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found")
            
            file_path = document.file_path
            file_type = document.file_type.lower().replace('.', '')
            
            # Validate file exists
            path_obj = Path(file_path)
            if not path_obj.exists() or not path_obj.is_file():
                logger.error(f"Document file not found on disk: {file_path}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Document file not found on disk: {path_obj.name}"
                )
            
            # Currently only support PPTX -> PDF conversion
            if file_type != 'pptx':
                raise HTTPException(
                    status_code=400,
                    detail=f"Preview not supported for file type: {file_type}. Currently only PPTX files are supported."
                )
            
            if format != 'pdf':
                raise HTTPException(
                    status_code=400,
                    detail=f"Preview format '{format}' not supported. Only 'pdf' is currently supported."
                )
            
            # Convert PPTX to PDF
            try:
                use_cache = settings.PPTX_CACHE_ENABLED and not force_refresh
                pdf_path = await pptx_converter.convert_pptx_to_pdf(
                    file_path,
                    use_cache=use_cache
                )
                
                # Return PDF file
                return FileResponse(
                    path=pdf_path,
                    media_type='application/pdf',
                    filename=f"{path_obj.stem}.pdf",
                    headers={
                        "X-Document-Id": str(document_id),
                        "X-Original-File": path_obj.name,
                        "X-Preview-Format": "pdf",
                        "X-Cache-Used": "true" if use_cache and pptx_converter.get_cached_pdf(file_path) else "false"
                    }
                )
                
            except FileNotFoundError as e:
                logger.error(f"PPTX file not found: {e}")
                raise HTTPException(status_code=404, detail=f"PPTX file not found: {str(e)}")
            except RuntimeError as e:
                logger.error(f"PPTX conversion failed: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to convert PPTX to PDF: {str(e)}"
                )
            except Exception as e:
                logger.error(f"Unexpected error during PPTX conversion: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Unexpected error during preview generation: {str(e)}"
                )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate preview for document {document_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate preview: {str(e)}"
        )

@app.get("/api/documents/{document_id}")
async def get_document_metadata(document_id: int):
    """
    Get document metadata by ID.
    Returns document information without the file content.
    """
    try:
        async for db_session in get_db():
            stmt = select(IndexedDocument).where(IndexedDocument.id == document_id)
            result = await db_session.execute(stmt)
            document = result.scalar_one_or_none()
            
            if not document:
                raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found")
            
            return {
                "status": "success",
                "document": {
                    "id": document.id,
                    "file_path": document.file_path,
                    "file_type": document.file_type,
                    "file_size": document.file_size,
                    "last_modified": document.last_modified.isoformat() if document.last_modified else None,
                    "content_preview": document.content_preview,
                    "chunks_count": document.chunks_count,
                    "processing_status": document.processing_status,
                    "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document metadata {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get document metadata: {str(e)}")

@app.get("/api/analytics/usage")
async def get_usage_analytics():
    """Get usage analytics and insights"""
    try:
        analytics = await db_service.get_usage_analytics()
        return {"status": "success", "analytics": analytics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Phase 3: Update Queue API Endpoints
@app.get("/api/updates/queue")
async def get_update_queue_status():
    """Get update queue status"""
    if not doc_processor or not hasattr(doc_processor, 'update_queue'):
        raise HTTPException(status_code=400, detail="Update queue not available")
    
    try:
        status = doc_processor.update_queue.get_status()
        pending_tasks = doc_processor.update_queue.get_pending_tasks(limit=10)
        
        return {
            "status": "success",
            "queue": {
                "pending": status["pending"],
                "processing": status["processing"],
                "completed": status["completed"],
                "failed": status["failed"],
                "pending_tasks": pending_tasks
            }
        }
    except Exception as e:
        logger.error(f"Failed to get update queue status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get update queue status: {str(e)}")

@app.get("/api/updates/status/{file_path:path}")
async def get_update_status(file_path: str):
    """Get update status for a specific file"""
    if not doc_processor or not hasattr(doc_processor, 'update_queue'):
        raise HTTPException(status_code=400, detail="Update queue not available")
    
    try:
        status = doc_processor.update_queue.get_status()
        
        # Check if file is in active updates
        active_file = None
        if file_path in doc_processor.update_queue.active_updates:
            task = doc_processor.update_queue.active_updates[file_path]
            active_file = {
                "file_path": task.file_path,
                "priority": task.priority,
                "update_type": task.update_type,
                "strategy": task.strategy.value if task.strategy else None,
                "enqueued_at": task.enqueued_at.isoformat()
            }
        
        # Check if file has completed update
        completed_result = None
        if file_path in doc_processor.update_queue.completed_updates:
            result = doc_processor.update_queue.completed_updates[file_path]
            completed_result = {
                "success": result.success,
                "chunks_updated": result.chunks_updated,
                "processing_time": result.processing_time,
                "completed_at": result.completed_at.isoformat() if result.completed_at else None,
                "error_message": result.error_message
            }
        
        return {
            "status": "success",
            "file_path": file_path,
            "active": active_file,
            "completed": completed_result
        }
    except Exception as e:
        logger.error(f"Failed to get update status for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get update status: {str(e)}")

@app.post("/api/updates/force")
async def force_update(request: dict):
    """Force update a file (high priority)"""
    if not doc_processor or not hasattr(doc_processor, 'enqueue_update'):
        raise HTTPException(status_code=400, detail="Update queue not available")
    
    file_path = request.get("file_path")
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path required")
    
    try:
        success = await doc_processor.enqueue_update(
            file_path=file_path,
            update_type="modified",
            user_requested=True  # High priority
        )
        
        if success:
            return {
                "status": "success",
                "message": f"Update enqueued for {file_path} with high priority"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to enqueue update (queue may be full)")
    except Exception as e:
        logger.error(f"Failed to force update {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to force update: {str(e)}")

# Phase 3: Server-Sent Events for real-time update notifications
@app.get("/api/updates/stream")
async def stream_update_status():
    """
    Server-Sent Events stream for real-time update queue status.
    Much more efficient than polling - only sends updates when status changes.
    """
    if not doc_processor or not hasattr(doc_processor, 'update_queue'):
        raise HTTPException(status_code=400, detail="Update queue not available")
    
    async def event_generator():
        """Generate SSE events when queue status changes"""
        last_status = None
        
        try:
            while True:
                # Get current status
                status = doc_processor.update_queue.get_status()
                current_status = {
                    "pending": status["pending"],
                    "processing": status["processing"],
                    "completed": status["completed"],
                    "failed": status["failed"]
                }
                
                # Only send event if status changed
                if current_status != last_status:
                    event_data = {
                        "status": "success",
                        "queue": current_status,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    
                    # Format as SSE
                    yield f"data: {json.dumps(event_data)}\n\n"
                    last_status = current_status
                
                # Check every 1 second (but only send when changed)
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logger.debug("SSE stream cancelled")
        except Exception as e:
            logger.error(f"Error in SSE stream: {e}")
            error_data = {"status": "error", "message": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable buffering for nginx
        }
    )