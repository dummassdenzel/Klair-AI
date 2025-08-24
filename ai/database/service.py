"""
Database service layer for document processor integration
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_, desc
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

from .models import ChatSession, ChatMessage, IndexedDocument, DocumentChatUsage
from .database import get_db

class DatabaseService:
    """Service for database operations"""
    
    def __init__(self):
        pass
    
    async def create_chat_session(self, directory_path: str, title: str = "New Chat") -> ChatSession:
        """Create a new chat session"""
        async for session in get_db():
            chat_session = ChatSession(
                title=title,
                directory_path=directory_path
            )
            session.add(chat_session)
            await session.commit()
            await session.refresh(chat_session)
            return chat_session
    
    async def add_chat_message(
        self, 
        session_id: int, 
        user_message: str, 
        ai_response: str, 
        sources: List[Dict], 
        response_time: float
    ) -> ChatMessage:
        """Add a chat message to a session"""
        async for session in get_db():
            chat_message = ChatMessage(
                session_id=session_id,
                user_message=user_message,
                ai_response=ai_response,
                sources=sources,
                response_time=response_time
            )
            session.add(chat_message)
            await session.commit()
            await session.refresh(chat_message)
            return chat_message
    
    async def store_document_metadata(
        self, 
        file_path: str, 
        file_hash: str, 
        file_type: str, 
        file_size: int, 
        last_modified: datetime,
        content_preview: str,
        chunks_count: int
    ) -> IndexedDocument:
        """Store or update document metadata"""
        async for session in get_db():
            # Check if document already exists
            stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
            result = await session.execute(stmt)
            existing_doc = result.scalar_one_or_none()
            
            if existing_doc:
                # Update existing document
                stmt = update(IndexedDocument).where(
                    IndexedDocument.file_path == file_path
                ).values(
                    file_hash=file_hash,
                    file_size=file_size,
                    last_modified=last_modified,
                    content_preview=content_preview,
                    chunks_count=chunks_count,
                    last_processed=datetime.utcnow(),
                    processing_status="indexed"
                )
                await session.execute(stmt)
                await session.commit()
                await session.refresh(existing_doc)
                return existing_doc
            else:
                # Create new document
                doc = IndexedDocument(
                    file_path=file_path,
                    file_hash=file_hash,
                    file_type=file_type,
                    file_size=file_size,
                    last_modified=last_modified,
                    content_preview=content_preview,
                    chunks_count=chunks_count
                )
                session.add(doc)
                await session.commit()
                await session.refresh(doc)
                return doc
    
    async def link_document_to_chat(
        self, 
        document_id: int, 
        chat_session_id: int
    ) -> DocumentChatUsage:
        """Link a document to a chat session usage"""
        async for session in get_db():
            # Check if usage already exists
            stmt = select(DocumentChatUsage).where(
                DocumentChatUsage.document_id == document_id,
                DocumentChatUsage.chat_session_id == chat_session_id
            )
            result = await session.execute(stmt)
            existing_usage = result.scalar_one_or_none()
            
            if existing_usage:
                # Update usage count and timestamp
                existing_usage.usage_count += 1
                existing_usage.last_used = datetime.utcnow()
                await session.commit()
                await session.refresh(existing_usage)
                return existing_usage
            else:
                # Create new usage record
                usage = DocumentChatUsage(
                    document_id=document_id,
                    chat_session_id=chat_session_id
                )
                session.add(usage)
                await session.commit()
                await session.refresh(usage)
                return usage
    
    async def get_chat_history(self, session_id: int) -> List[ChatMessage]:
        """Get chat history for a session"""
        async for session in get_db():
            stmt = select(ChatMessage).where(
                ChatMessage.session_id == session_id
            ).order_by(ChatMessage.timestamp)
            result = await session.execute(stmt)
            return result.scalars().all()
    
    async def get_document_stats(self) -> Dict[str, Any]:
        """Get statistics about indexed documents"""
        async for session in get_db():
            try:
                # Count total documents
                total_docs = await session.scalar(select(func.count(IndexedDocument.id)))
                
                # Count by status
                status_result = await session.execute(
                    select(
                        IndexedDocument.processing_status,
                        func.count(IndexedDocument.id)
                    ).group_by(IndexedDocument.processing_status)
                )
                status_breakdown = dict(status_result.all())
                
                # Count by file type
                type_result = await session.execute(
                    select(
                        IndexedDocument.file_type,
                        func.count(IndexedDocument.id)
                    ).group_by(IndexedDocument.file_type)
                )
                type_breakdown = dict(type_result.all())
                
                return {
                    "total_documents": total_docs or 0,
                    "status_breakdown": status_breakdown,
                    "type_breakdown": type_breakdown
                }
            except Exception as e:
                raise e
    
    # NEW: Chat Session Management Methods
    
    async def get_chat_sessions_by_directory(self, directory_path: str) -> List[Dict[str, Any]]:
        """Get all chat sessions for a specific directory"""
        async for session in get_db():
            stmt = select(ChatSession).where(
                ChatSession.directory_path == directory_path
            ).order_by(desc(ChatSession.updated_at))
            
            result = await session.execute(stmt)
            chat_sessions = result.scalars().all()
            
            # Convert to dictionaries with message count
            sessions_data = []
            for chat_session in chat_sessions:
                # Get message count for this session
                msg_count = await session.scalar(
                    select(func.count(ChatMessage.id)).where(
                        ChatMessage.session_id == chat_session.id
                    )
                )
                
                sessions_data.append({
                    "id": chat_session.id,
                    "title": chat_session.title,
                    "directory_path": chat_session.directory_path,
                    "created_at": chat_session.created_at.isoformat(),
                    "updated_at": chat_session.updated_at.isoformat(),
                    "message_count": msg_count or 0
                })
            
            return sessions_data
    
    async def delete_chat_session(self, session_id: int) -> bool:
        """Delete a chat session and all its messages"""
        async for session in get_db():
            try:
                # Delete the chat session (cascade will handle messages)
                stmt = select(ChatSession).where(ChatSession.id == session_id)
                result = await session.execute(stmt)
                chat_session = result.scalar_one_or_none()
                
                if not chat_session:
                    return False
                
                await session.delete(chat_session)
                await session.commit()
                return True
                
            except Exception as e:
                await session.rollback()
                raise e
    
    async def update_chat_session_title(self, session_id: int, new_title: str) -> bool:
        """Update the title of a chat session"""
        async for session in get_db():
            try:
                stmt = update(ChatSession).where(
                    ChatSession.id == session_id
                ).values(title=new_title, updated_at=datetime.utcnow())
                
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount > 0
                
            except Exception as e:
                await session.rollback()
                raise e
    
    # NEW: Document Search & Filtering Methods
    
    async def search_documents(
        self, 
        query: str = "", 
        file_type: str = "", 
        date_from: str = "", 
        date_to: str = "",
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Search documents with various filters"""
        async for session in get_db():
            try:
                # Build the base query
                stmt = select(IndexedDocument)
                conditions = []
                
                # Text search in file path and content preview
                if query:
                    conditions.append(
                        or_(
                            IndexedDocument.file_path.ilike(f"%{query}%"),
                            IndexedDocument.content_preview.ilike(f"%{query}%")
                        )
                    )
                
                # File type filter
                if file_type:
                    conditions.append(IndexedDocument.file_type == file_type.lower())
                
                # Date range filter
                if date_from:
                    try:
                        from_date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                        conditions.append(IndexedDocument.last_modified >= from_date)
                    except ValueError:
                        pass
                
                if date_to:
                    try:
                        to_date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                        conditions.append(IndexedDocument.last_modified <= to_date)
                    except ValueError:
                        pass
                
                # Apply conditions
                if conditions:
                    stmt = stmt.where(and_(*conditions))
                
                # Add pagination
                stmt = stmt.order_by(desc(IndexedDocument.indexed_at)).limit(limit).offset(offset)
                
                # Execute query
                result = await session.execute(stmt)
                documents = result.scalars().all()
                
                # Get total count for pagination
                count_stmt = select(func.count(IndexedDocument.id))
                if conditions:
                    count_stmt = count_stmt.where(and_(*conditions))
                
                total_count = await session.scalar(count_stmt)
                
                # Convert to dictionaries
                docs_data = []
                for doc in documents:
                    docs_data.append({
                        "id": doc.id,
                        "file_path": doc.file_path,
                        "file_type": doc.file_type,
                        "file_size": doc.file_size,
                        "last_modified": doc.last_modified.isoformat() if doc.last_modified else None,
                        "content_preview": doc.content_preview,
                        "chunks_count": doc.chunks_count,
                        "processing_status": doc.processing_status,
                        "indexed_at": doc.indexed_at.isoformat() if doc.indexed_at else None
                    })
                
                return {
                    "documents": docs_data,
                    "total_count": total_count,
                    "limit": limit,
                    "offset": offset,
                    "has_more": (offset + limit) < total_count
                }
                
            except Exception as e:
                raise e
    
    async def get_documents_by_type(self, file_type: str) -> List[IndexedDocument]:
        """Get all documents of a specific type"""
        async for session in get_db():
            stmt = select(IndexedDocument).where(
                IndexedDocument.file_type == file_type.lower()
            ).order_by(desc(IndexedDocument.indexed_at))
            
            result = await session.execute(stmt)
            return result.scalars().all()
    
    async def get_recent_documents(self, days: int = 7) -> List[IndexedDocument]:
        """Get documents indexed in the last N days"""
        async for session in get_db():
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            stmt = select(IndexedDocument).where(
                IndexedDocument.indexed_at >= cutoff_date
            ).order_by(desc(IndexedDocument.indexed_at))
            
            result = await session.execute(stmt)
            return result.scalars().all()
    
    # NEW: Analytics & Insights Methods
    
    async def get_usage_analytics(self) -> Dict[str, Any]:
        """Get comprehensive usage analytics and insights"""
        async for session in get_db():
            try:
                # Document statistics
                total_docs = await session.scalar(select(func.count(IndexedDocument.id)))
                
                # File type breakdown
                type_breakdown = await session.execute(
                    select(
                        IndexedDocument.file_type,
                        func.count(IndexedDocument.id)
                    ).group_by(IndexedDocument.file_type)
                )
                
                # Status breakdown
                status_breakdown = await session.execute(
                    select(
                        IndexedDocument.processing_status,
                        func.count(IndexedDocument.id)
                    ).group_by(IndexedDocument.processing_status)
                )
                
                # Chat session statistics
                total_sessions = await session.scalar(select(func.count(ChatSession.id)))
                total_messages = await session.scalar(select(func.count(ChatMessage.id)))
                
                # Average response time
                avg_response_time = await session.scalar(
                    select(func.avg(ChatMessage.response_time))
                )
                
                # Most used documents
                most_used_docs = await session.execute(
                    select(
                        IndexedDocument.file_path,
                        func.count(DocumentChatUsage.document_id).label('usage_count')
                    ).join(DocumentChatUsage).group_by(IndexedDocument.id).order_by(
                        desc('usage_count')
                    ).limit(10)
                )
                
                # Recent activity (last 7 days)
                week_ago = datetime.utcnow() - timedelta(days=7)
                recent_sessions = await session.scalar(
                    select(func.count(ChatSession.id)).where(
                        ChatSession.created_at >= week_ago
                    )
                )
                
                recent_messages = await session.scalar(
                    select(func.count(ChatMessage.id)).where(
                        ChatMessage.timestamp >= week_ago
                    )
                )
                
                return {
                    "document_stats": {
                        "total_documents": total_docs or 0,
                        "type_breakdown": dict(type_breakdown.all()),
                        "status_breakdown": dict(status_breakdown.all())
                    },
                    "chat_stats": {
                        "total_sessions": total_sessions or 0,
                        "total_messages": total_messages or 0,
                        "average_response_time": float(avg_response_time) if avg_response_time else 0,
                        "recent_sessions_7d": recent_sessions or 0,
                        "recent_messages_7d": recent_messages or 0
                    },
                    "usage_insights": {
                        "most_used_documents": [
                            {"file_path": doc.file_path, "usage_count": doc.usage_count}
                            for doc in most_used_docs.all()
                        ]
                    }
                }
                
            except Exception as e:
                raise e
    
    async def get_document_processing_stats(self) -> Dict[str, Any]:
        """Get detailed document processing statistics"""
        async for session in get_db():
            try:
                # Processing time statistics
                processing_stats = await session.execute(
                    select(
                        IndexedDocument.processing_status,
                        func.count(IndexedDocument.id),
                        func.avg(func.extract('epoch', IndexedDocument.last_processed - IndexedDocument.indexed_at))
                    ).group_by(IndexedDocument.processing_status)
                )
                
                # File size statistics
                size_stats = await session.execute(
                    select(
                        func.avg(IndexedDocument.file_size),
                        func.min(IndexedDocument.file_size),
                        func.max(IndexedDocument.file_size),
                        func.sum(IndexedDocument.file_size)
                    )
                )
                
                # Chunk statistics
                chunk_stats = await session.execute(
                    select(
                        func.avg(IndexedDocument.chunks_count),
                        func.min(IndexedDocument.chunks_count),
                        func.max(IndexedDocument.chunks_count),
                        func.sum(IndexedDocument.chunks_count)
                    )
                )
                
                return {
                    "processing_stats": [
                        {
                            "status": stat[0],
                            "count": stat[1],
                            "avg_processing_time_seconds": float(stat[2]) if stat[2] else 0
                        }
                        for stat in processing_stats.all()
                    ],
                    "file_size_stats": {
                        "average_bytes": float(size_stats.scalar()[0]) if size_stats.scalar()[0] else 0,
                        "min_bytes": size_stats.scalar()[1] or 0,
                        "max_bytes": size_stats.scalar()[2] or 0,
                        "total_bytes": size_stats.scalar()[3] or 0
                    },
                    "chunk_stats": {
                        "average_chunks": float(chunk_stats.scalar()[0]) if chunk_stats.scalar()[0] else 0,
                        "min_chunks": chunk_stats.scalar()[1] or 0,
                        "max_chunks": chunk_stats.scalar()[2] or 0,
                        "total_chunks": chunk_stats.scalar()[3] or 0
                    }
                }
                
            except Exception as e:
                raise e
    
    async def get_chat_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get chat-specific analytics for the last N days"""
        async for session in get_db():
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                
                # Messages per day
                daily_messages = await session.execute(
                    select(
                        func.date(ChatMessage.timestamp).label('date'),
                        func.count(ChatMessage.id)
                    ).where(
                        ChatMessage.timestamp >= cutoff_date
                    ).group_by(
                        func.date(ChatMessage.timestamp)
                    ).order_by('date')
                )
                
                # Response time trends
                response_time_trends = await session.execute(
                    select(
                        func.date(ChatMessage.timestamp).label('date'),
                        func.avg(ChatMessage.response_time)
                    ).where(
                        ChatMessage.timestamp >= cutoff_date
                    ).group_by(
                        func.date(ChatMessage.timestamp)
                    ).order_by('date')
                )
                
                # Most active directories
                active_directories = await session.execute(
                    select(
                        ChatSession.directory_path,
                        func.count(ChatSession.id)
                    ).where(
                        ChatSession.created_at >= cutoff_date
                    ).group_by(
                        ChatSession.directory_path
                    ).order_by(
                        desc(func.count(ChatSession.id))
                    ).limit(10)
                )
                
                return {
                    "daily_messages": [
                        {"date": str(day.date), "count": day.count}
                        for day in daily_messages.all()
                    ],
                    "response_time_trends": [
                        {"date": str(day.date), "avg_response_time": float(day.avg) if day.avg else 0}
                        for day in response_time_trends.all()
                    ],
                    "active_directories": [
                        {"directory": dir.dir_path, "session_count": dir.count}
                        for dir in active_directories.all()
                    ]
                }
                
            except Exception as e:
                raise e