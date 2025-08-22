from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, default="New Chat")
    directory_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    messages = relationship("ChatMessage", back_populates="session")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"))
    user_message = Column(Text, nullable=False)
    ai_response = Column(Text, nullable=False)
    sources = Column(JSON)  # Store source document metadata
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    session = relationship("ChatSession", back_populates="messages")

class IndexedDocument(Base):
    __tablename__ = "indexed_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, unique=True, nullable=False)
    file_hash = Column(String, nullable=False)
    file_size = Column(Integer)
    last_modified = Column(DateTime)
    content_preview = Column(Text)  # First 500 chars for preview
    indexed_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="indexed")  # indexed, error, processing