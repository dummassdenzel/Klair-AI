from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
import asyncio
import logging
from services.document_processor import DocumentProcessorOrchestrator, config
from config import settings
from services.file_monitor import FileMonitorService
from schemas.chat import ChatRequest, ChatResponse

# NEW: Add database imports
from database import DatabaseService, get_db
from database.models import ChatSession, ChatMessage, IndexedDocument
from datetime import datetime
from sqlalchemy import select, func, or_, and_, desc

# Configure logging
logging.basicConfig(level=logging.INFO)
for noisy in [
    "sqlalchemy.engine",
    "httpx",
    "chromadb",
    "watchdog.observers.inotify",
]:
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Global state
doc_processor: Optional[DocumentProcessorOrchestrator] = None
file_monitor: Optional[FileMonitorService] = None
current_directory: Optional[str] = None
prewarming_complete = False
prewarming_task = None
 
# NEW: Add database service
db_service = DatabaseService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global prewarming_complete, prewarming_task
    
    # Startup
    logger.info("Starting AI Document Assistant...")
    
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

@app.post("/api/set-directory")
async def set_directory(request: dict):
    """Set the directory to monitor and process documents from"""
    global doc_processor, file_monitor, current_directory
    
    directory_path = request.get("path")
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path required")
    
    try:
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
        
        # Start file monitoring immediately
        file_monitor = FileMonitorService(doc_processor)
        await file_monitor.start_monitoring(directory_path)
        
        current_directory = directory_path
        
        # Process existing documents in background
        asyncio.create_task(
            doc_processor.initialize_from_directory(directory_path)
        )
        
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
        
        # Query RAG system
        response = await doc_processor.query(request.message)
        
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
        
        logger.info(f"Query completed in {response.response_time}s with {len(response.sources)} sources")
        
        return ChatResponse(
            message=response.message,
            sources=response.sources
        )
        
    except Exception as e:
        logger.error(f"Query failed: {e}")
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

@app.get("/api/analytics/usage")
async def get_usage_analytics():
    """Get usage analytics and insights"""
    try:
        analytics = await db_service.get_usage_analytics()
        return {"status": "success", "analytics": analytics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))