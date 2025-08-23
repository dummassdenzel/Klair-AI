from fastapi import FastAPI, HTTPException
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
async def set_directory(request: dict):
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
        
        # Start file monitoring
        async def on_file_change(file_path: str, is_deletion: bool = False):
            """Async callback for file changes"""
            try:
                if is_deletion:
                    await doc_processor.remove_document(file_path)
                else:
                    await doc_processor.add_document(file_path)
                print(f"🔄 File change processed: {file_path} (deletion: {is_deletion})")
            except Exception as e:
                print(f"❌ Error processing file change {file_path}: {e}")
        
        event_handler = DocumentFileHandler(on_file_change)
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
        "observer_running": file_observer is not None and file_observer.is_alive() if file_observer else False,
        "index_stats": doc_processor.get_index_stats() if doc_processor else None
    }

@app.post("/api/clear-index")
async def clear_index():
    """Clear the entire index (for testing)"""
    global doc_processor
    if doc_processor:
        try:
            # Get all documents first
            all_results = doc_processor.collection.get()
            if all_results['ids']:
                # Delete by IDs
                doc_processor.collection.delete(ids=all_results['ids'])
                print(f"Cleared {len(all_results['ids'])} documents")
            
            doc_processor.file_hashes.clear()
            return {"status": "success", "message": "Index cleared"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to clear index: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="No processor initialized")