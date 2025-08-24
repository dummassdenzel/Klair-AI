from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import asyncio
from services.document_processor import DocumentProcessor
from services.file_monitor import FileMonitorService  # Updated import
from schemas.chat import ChatRequest, ChatResponse

# Global state
doc_processor: Optional[DocumentProcessor] = None
file_monitor: Optional[FileMonitorService] = None  # Updated
current_directory: Optional[str] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    global file_monitor
    if file_monitor:
        await file_monitor.stop_monitoring()  # Updated cleanup

app = FastAPI(
    title="AI Document Assistant",
    description="RAG-powered document chat assistant",
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
    global doc_processor, file_monitor, current_directory
    
    directory_path = request.get("path")
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path required")
    
    try:
        # Stop existing file monitor
        if file_monitor:
            await file_monitor.stop_monitoring()
        
        # Initialize document processor
        doc_processor = DocumentProcessor()
        await doc_processor.initialize_from_directory(directory_path)
        
        # Start file monitoring with new service
        file_monitor = FileMonitorService(doc_processor)
        await file_monitor.start_monitoring(directory_path)
        
        current_directory = directory_path
        
        # Get stats using new method
        stats = doc_processor.get_stats()
        
        return {
            "status": "success",
            "directory": directory_path,
            "indexed_files": stats["total_files"],
            "total_chunks": stats["total_chunks"],
            "stats": stats
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set directory: {str(e)}")

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if not doc_processor:
        raise HTTPException(status_code=400, detail="No directory set")
    
    try:
        # Query RAG system
        response = await doc_processor.query(request.message)
        
        return ChatResponse(
            message=response.message,
            sources=response.sources
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

@app.get("/api/status")
async def get_status():
    """Get current system status"""
    return {
        "directory_set": current_directory is not None,
        "current_directory": current_directory,
        "processor_ready": doc_processor is not None,
        "monitor_running": file_monitor is not None and file_monitor.is_running if file_monitor else False,
        "index_stats": doc_processor.get_stats() if doc_processor else None
    }

@app.post("/api/clear-index")
async def clear_index():
    """Clear the entire index (for testing)"""
    global doc_processor
    if doc_processor:
        try:
            await doc_processor._clear_collection()
            doc_processor.file_hashes.clear()
            doc_processor.file_metadata.clear()
            return {"status": "success", "message": "Index cleared"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to clear index: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="No processor initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global doc_processor, file_monitor
    if file_monitor:
        await file_monitor.stop_monitoring()
    if doc_processor:
        await doc_processor.cleanup()