from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import asyncio
from services.document_processor import DocumentProcessor
from services.file_monitor import DocumentFileHandler, Observer
from schemas.chat import ChatRequest, ChatResponse

# Global state
doc_processor: Optional[DocumentProcessor] = None
file_observer: Optional[Observer] = None
current_directory: Optional[str] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    global file_observer
    if file_observer:
        # Clean up file handler
        for handler in file_observer.emitters.values():
            for event_handler in handler:
                if hasattr(event_handler, 'cleanup'):
                    event_handler.cleanup()
        
        file_observer.stop()
        file_observer.join()

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
async def set_directory(request: dict, background_tasks: BackgroundTasks):
    global doc_processor, file_observer, current_directory
    
    directory_path = request.get("path")
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path required")
    
    try:
        # Stop existing observer
        if file_observer:
            file_observer.stop()
            file_observer.join()
        
        # Initialize document processor
        doc_processor = DocumentProcessor()
        await doc_processor.initialize_from_directory(directory_path)
        
        # Start file monitoring with proper event loop
        def on_file_change(file_path: str, is_deletion: bool = False):
            if is_deletion:
                background_tasks.add_task(doc_processor.remove_document, file_path)
            else:
                background_tasks.add_task(doc_processor.update_document, file_path)
        
        event_handler = DocumentFileHandler(on_file_change)
        # Set the current event loop
        event_handler.set_event_loop(asyncio.get_running_loop())
        
        file_observer = Observer()
        file_observer.schedule(event_handler, directory_path, recursive=True)
        file_observer.start()
        
        current_directory = directory_path
        
        # Get index stats
        stats = doc_processor.get_index_stats()
        
        return {
            "status": "success",
            "directory": directory_path,
            "indexed_files": len(doc_processor.get_indexed_files()),
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
        
        # Process response safely
        response_text = str(response)
        
        # Handle sources safely
        sources = []
        if hasattr(response, 'source_nodes') and response.source_nodes:
            for node in response.source_nodes:
                sources.append({
                    "file_path": getattr(node.metadata, 'get', lambda x, y='': y)("file_path", ""),
                    "relevance_score": getattr(node, 'score', 0.0),
                    "content_snippet": getattr(node, 'text', '')[:200] + "..."
                })
        
        return ChatResponse(
            message=response_text,
            sources=sources
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
        "observer_running": file_observer is not None and file_observer.is_alive() if file_observer else False,
        "index_stats": doc_processor.get_index_stats() if doc_processor else None
    }