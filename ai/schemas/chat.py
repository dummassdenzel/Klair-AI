from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class ChatRequest(BaseModel):
    session_id: int
    message: str

class SourceInfo(BaseModel):
    file_path: str
    relevance_score: float
    content_snippet: str

class ChatResponse(BaseModel):
    message: str
    sources: List[SourceInfo]
