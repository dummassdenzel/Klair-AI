"""
Database package for AI Document Assistant
"""

from .database import Base, get_db, test_connection
from .models import ChatSession, ChatMessage, IndexedDocument, DocumentChatUsage
from .service import DatabaseService

__all__ = [
    "Base",
    "get_db", 
    "test_connection",
    "ChatSession",
    "ChatMessage", 
    "IndexedDocument",
    "DocumentChatUsage",
    "DatabaseService"
]