from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from services.document_processor import DocumentProcessor
from services.file_monitor import DocumentFileHandler, Observer
from database.models import ChatSession, ChatMessage
from database.database import get_db
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
    
    return {
        "status": "success",
        "directory": directory_path,
        "indexed_files": len(doc_processor.get_indexed_files())
    }

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    if not doc_processor:
        raise HTTPException(status_code=400, detail="No directory set")
    
    # Query RAG system
    response = await doc_processor.query(request.message)
    
    # Save to database
    chat_message = ChatMessage(
        session_id=request.session_id,
        user_message=request.message,
        ai_response=str(response),
        sources=[node.metadata for node in response.source_nodes]
    )
    db.add(chat_message)
    await db.commit()
    
    return ChatResponse(
        message=str(response),
        sources=[{
            "file_path": node.metadata.get("file_path", ""),
            "relevance_score": node.score,
            "content_snippet": node.text[:200] + "..."
        } for node in response.source_nodes]
    )