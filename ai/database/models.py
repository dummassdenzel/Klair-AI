from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, ForeignKey, BigInteger, Float
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
from .database import Base

class ChatSession(Base):
    __tablename__ = "chat_sessions"
     
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, default="New Chat")
    directory_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    
    # NEW: Add cascade for document usage
    document_usage = relationship("DocumentChatUsage", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"))
    user_message = Column(Text, nullable=False)
    ai_response = Column(Text, nullable=False)
    sources = Column(JSON)  # Store source document metadata
    response_time = Column(Float)  # Response time in seconds
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    session = relationship("ChatSession", back_populates="messages")

class IndexedDocument(Base):
    __tablename__ = "indexed_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, unique=True, nullable=False, index=True)
    file_hash = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_size = Column(BigInteger)
    last_modified = Column(DateTime)
    content_preview = Column(Text)  # First 500 chars for preview
    chunks_count = Column(Integer, default=0)
    processing_status = Column(String, default="indexed")  # indexed, error, processing
    indexed_at = Column(DateTime, default=datetime.utcnow)
    last_processed = Column(DateTime, default=datetime.utcnow)
    
    # Add relationship to chat sessions that used this document
    chat_sessions = relationship("ChatSession", secondary="document_chat_usage")

class DocumentChatUsage(Base):
    """Many-to-many relationship between documents and chat sessions"""
    __tablename__ = "document_chat_usage"
    
    document_id = Column(Integer, ForeignKey("indexed_documents.id", ondelete="CASCADE"), primary_key=True)
    chat_session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True)
    usage_count = Column(Integer, default=1)
    first_used = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)