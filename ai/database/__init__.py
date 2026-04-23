"""
Database package for AI Document Assistant
"""

from .database import Base, test_connection, create_tables, AsyncSessionLocal
from .models import ChatSession, ChatMessage, IndexedDocument, DocumentChatUsage
from .service import DatabaseService

__all__ = [
    "Base",
    "test_connection",
    "create_tables",
    "AsyncSessionLocal",
    "ChatSession",
    "ChatMessage",
    "IndexedDocument",
    "DocumentChatUsage",
    "DatabaseService",
]