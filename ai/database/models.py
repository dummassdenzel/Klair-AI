from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (no tzinfo).
    PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns require naive datetimes;
    asyncpg rejects timezone-aware values for those columns."""
    return datetime.utcnow()


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, default="New Chat")
    directory_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")

    document_usage = relationship("DocumentChatUsage", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"))
    user_message = Column(Text, nullable=False)
    ai_response = Column(Text, nullable=False)
    sources = Column(JSON)
    response_time = Column(Float)
    timestamp = Column(DateTime, default=_utcnow)

    session = relationship("ChatSession", back_populates="messages")

class IndexedDocument(Base):
    __tablename__ = "indexed_documents"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, unique=True, nullable=False, index=True)
    file_hash = Column(String, nullable=False)
    file_type = Column(String, nullable=False, index=True)
    file_size = Column(Integer)
    last_modified = Column(DateTime, index=True)
    content_preview = Column(Text)
    document_category = Column(String, nullable=True, index=True)
    chunks_count = Column(Integer, default=0)
    processing_status = Column(String, default="indexed", index=True)
    indexed_at = Column(DateTime, default=_utcnow, index=True)
    last_processed = Column(DateTime, default=_utcnow)

    chat_sessions = relationship("ChatSession", secondary="document_chat_usage", overlaps="document_usage")

class DocumentChatUsage(Base):
    """Many-to-many relationship between documents and chat sessions"""
    __tablename__ = "document_chat_usage"

    document_id = Column(Integer, ForeignKey("indexed_documents.id", ondelete="CASCADE"), primary_key=True)
    chat_session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True)
    usage_count = Column(Integer, default=1)
    first_used = Column(DateTime, default=_utcnow)
    last_used = Column(DateTime, default=_utcnow, onupdate=_utcnow)