from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import asyncio

from .services.document_manager import DocumentManager
from .services.file_monitor import DocumentFileHandler, Observer
from .database.models import ChatSession, ChatMessage
from .database.database import get_db
from .schemas.chat import ChatRequest, ChatResponse

# Global state
doc_manager: Optional[DocumentManager] = None
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
async def set_directory(request: dict, background_tasks: BackgroundTasks):
    global doc_manager, file_observer, current_directory
    
    directory_path = request.get("path")
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path required")
    
    # Stop existing observer
    if file_observer:
        file_observer.stop()
        file_observer.join()
    
    # Initialize document manager
    doc_manager = DocumentManager()
    await doc_manager.initialize_from_directory(directory_path)
    
    # Start file monitoring
    def on_file_change(file_path: str):
        background_tasks.add_task(doc_manager.update_document, file_path)
    
    event_handler = DocumentFileHandler(on_file_change)
    file_observer = Observer()
    file_observer.schedule(event_handler, directory_path, recursive=True)
    file_observer.start()
    
    current_directory = directory_path
    
    return {
        "status": "success",
        "directory": directory_path,
        "indexed_files": len(doc_manager.get_indexed_files())
    }

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    if not doc_manager:
        raise HTTPException(status_code=400, detail="No directory set")
    
    # Query RAG system
    response = await doc_manager.query(request.message)
    
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