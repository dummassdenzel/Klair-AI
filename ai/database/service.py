"""
Database service layer for document processor integration
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_, desc
from sqlalchemy.sql.expression import literal
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

from .models import ChatSession, ChatMessage, IndexedDocument, DocumentChatUsage
from .database import AsyncSessionLocal
from utils import utc_isoformat

class DatabaseService:
    """Service for database operations"""
    
    def __init__(self):
        pass
    
    async def create_chat_session(self, directory_path: str, title: str = "New Chat") -> ChatSession:
        """Create a new chat session"""
        import os
        normalized_path = os.path.normpath(os.path.abspath(directory_path)) if directory_path else directory_path
        async with AsyncSessionLocal() as session:
            try:
                chat_session = ChatSession(title=title, directory_path=normalized_path)
                session.add(chat_session)
                await session.commit()
                await session.refresh(chat_session)
                return chat_session
            except Exception:
                await session.rollback()
                raise
    
    async def add_chat_message(
        self,
        session_id: int,
        user_message: str,
        ai_response: str,
        sources: List[Dict],
        response_time: float
    ) -> ChatMessage:
        """Add a chat message to a session"""
        async with AsyncSessionLocal() as session:
            try:
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
            except Exception:
                await session.rollback()
                raise
    
    async def store_document_metadata(
        self,
        file_path: str,
        file_hash: str,
        file_type: str,
        file_size: int,
        last_modified: datetime,
        content_preview: str = "",
        chunks_count: int = 0,
        processing_status: str = "indexed"
    ) -> IndexedDocument:
        """Store or update document metadata"""
        async with AsyncSessionLocal() as session:
            try:
                stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
                result = await session.execute(stmt)
                existing_doc = result.scalar_one_or_none()
                if existing_doc:
                    stmt = update(IndexedDocument).where(
                        IndexedDocument.file_path == file_path
                    ).values(
                        file_hash=file_hash,
                        file_size=file_size,
                        last_modified=last_modified,
                        content_preview=content_preview,
                        chunks_count=chunks_count,
                        last_processed=datetime.utcnow(),
                        processing_status=processing_status
                    )
                    await session.execute(stmt)
                    await session.commit()
                    await session.refresh(existing_doc)
                    return existing_doc
                doc = IndexedDocument(
                    file_path=file_path,
                    file_hash=file_hash,
                    file_type=file_type,
                    file_size=file_size,
                    last_modified=last_modified,
                    content_preview=content_preview,
                    chunks_count=chunks_count,
                    processing_status=processing_status
                )
                session.add(doc)
                await session.commit()
                await session.refresh(doc)
                return doc
            except Exception:
                await session.rollback()
                raise
    
    async def store_metadata_only(
        self,
        file_path: str,
        file_hash: str,
        file_type: str,
        file_size: int,
        last_modified: datetime
    ) -> IndexedDocument:
        """Store only metadata (fast, for metadata-first indexing)"""
        return await self.store_document_metadata(
            file_path=file_path,
            file_hash=file_hash,
            file_type=file_type,
            file_size=file_size,
            last_modified=last_modified,
            content_preview="",  # Empty until content is indexed
            chunks_count=0,  # Zero until content is indexed
            processing_status="metadata_only"  # Indicates content not yet indexed
        )

    async def set_documents_indexed(self, file_paths: List[str]) -> int:
        """Set processing_status='indexed' for all given file paths. Returns count updated. Used after background indexing to ensure DB is consistent."""
        if not file_paths:
            return 0
        async with AsyncSessionLocal() as session:
            try:
                stmt = (
                    update(IndexedDocument)
                    .where(IndexedDocument.file_path.in_(file_paths))
                    .values(processing_status="indexed", last_processed=datetime.utcnow())
                )
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount or 0
            except Exception:
                await session.rollback()
                raise

    async def get_document_by_path(self, file_path: str) -> Optional[IndexedDocument]:
        """Get a single document by file path (for hash/metadata lookup)."""
        async with AsyncSessionLocal() as session:
            stmt = select(IndexedDocument).where(IndexedDocument.file_path == file_path)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
    
    async def link_document_to_chat(
        self,
        document_id: int,
        chat_session_id: int
    ) -> DocumentChatUsage:
        """Link a document to a chat session usage"""
        async with AsyncSessionLocal() as session:
            try:
                stmt = select(DocumentChatUsage).where(
                    DocumentChatUsage.document_id == document_id,
                    DocumentChatUsage.chat_session_id == chat_session_id
                )
                result = await session.execute(stmt)
                existing_usage = result.scalar_one_or_none()
                if existing_usage:
                    existing_usage.usage_count += 1
                    existing_usage.last_used = datetime.utcnow()
                    await session.commit()
                    await session.refresh(existing_usage)
                    return existing_usage
                usage = DocumentChatUsage(
                    document_id=document_id,
                    chat_session_id=chat_session_id
                )
                session.add(usage)
                await session.commit()
                await session.refresh(usage)
                return usage
            except Exception:
                await session.rollback()
                raise
    
    async def get_chat_history(self, session_id: int) -> List[ChatMessage]:
        """Get chat history for a session"""
        async with AsyncSessionLocal() as session:
            stmt = select(ChatMessage).where(
                ChatMessage.session_id == session_id
            ).order_by(ChatMessage.timestamp)
            result = await session.execute(stmt)
            return result.scalars().all()
    
    async def get_document_stats(self) -> Dict[str, Any]:
        """Get statistics about indexed documents"""
        async with AsyncSessionLocal() as session:
            total_docs = await session.scalar(select(func.count(IndexedDocument.id)))
            status_result = await session.execute(
                select(
                    IndexedDocument.processing_status,
                    func.count(IndexedDocument.id)
                ).group_by(IndexedDocument.processing_status)
            )
            status_breakdown = dict(status_result.all())
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

    async def get_indexed_file_paths(self, limit: int = 500) -> List[str]:
        """Get list of indexed file paths (for stats). Capped for memory safety."""
        async with AsyncSessionLocal() as session:
            stmt = select(IndexedDocument.file_path).where(
                IndexedDocument.processing_status.in_(["indexed", "metadata_only"])
            ).limit(limit)
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    # NEW: Chat Session Management Methods
    
    async def get_chat_sessions_by_directory(self, directory_path: str) -> List[Dict[str, Any]]:
        """Get all chat sessions for a specific directory (with path normalization)"""
        import os
        # Normalize directory path for comparison (handle different path formats)
        normalized_path = os.path.normpath(os.path.abspath(directory_path)) if directory_path else ""
        
        async with AsyncSessionLocal() as session:
            stmt = select(ChatSession).order_by(desc(ChatSession.updated_at))
            result = await session.execute(stmt)
            all_sessions = result.scalars().all()
            matching_sessions = [
                cs for cs in all_sessions
                if (os.path.normpath(os.path.abspath(cs.directory_path or "")) == normalized_path)
            ]
            sessions_data = []
            for chat_session in matching_sessions:
                msg_count = await session.scalar(
                    select(func.count(ChatMessage.id)).where(
                        ChatMessage.session_id == chat_session.id
                    )
                )
                sessions_data.append({
                    "id": chat_session.id,
                    "title": chat_session.title,
                    "directory_path": chat_session.directory_path,
                    "created_at": utc_isoformat(chat_session.created_at),
                    "updated_at": utc_isoformat(chat_session.updated_at),
                    "message_count": msg_count or 0
                })
            return sessions_data
    
    async def delete_chat_session(self, session_id: int) -> bool:
        """Delete a chat session and all its messages"""
        async with AsyncSessionLocal() as session:
            try:
                stmt = select(ChatSession).where(ChatSession.id == session_id)
                result = await session.execute(stmt)
                chat_session = result.scalar_one_or_none()
                if not chat_session:
                    return False
                await session.delete(chat_session)
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                raise
    
    async def update_chat_session_title(self, session_id: int, new_title: str) -> bool:
        """Update the title of a chat session"""
        async with AsyncSessionLocal() as session:
            try:
                stmt = update(ChatSession).where(
                    ChatSession.id == session_id
                ).values(title=new_title, updated_at=datetime.utcnow())
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount > 0
            except Exception:
                await session.rollback()
                raise
    
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
        """Search documents with various filters. Uses one query with a window count for total."""
        async with AsyncSessionLocal() as session:
            conditions = []
            if query:
                search_val = func.lower(literal(query))
                conditions.append(
                    or_(
                        func.lower(IndexedDocument.file_path).contains(search_val),
                        func.lower(IndexedDocument.content_preview).contains(search_val)
                    )
                )
            if file_type:
                conditions.append(IndexedDocument.file_type == file_type.lower())
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

            # Single query: rows + total count via window function (avoids separate count query)
            stmt = select(
                IndexedDocument,
                func.count(IndexedDocument.id).over().label("total_count"),
            )
            if conditions:
                stmt = stmt.where(and_(*conditions))
            stmt = stmt.order_by(desc(IndexedDocument.indexed_at)).limit(limit).offset(offset)
            result = await session.execute(stmt)
            rows = result.all()

            total_count = int(rows[0].total_count) if rows else 0
            documents = [row[0] for row in rows]
            docs_data = [
                {
                    "id": doc.id,
                    "file_path": doc.file_path,
                    "file_type": doc.file_type,
                    "file_size": doc.file_size,
                    "last_modified": utc_isoformat(doc.last_modified),
                    "content_preview": doc.content_preview,
                    "chunks_count": doc.chunks_count,
                    "processing_status": doc.processing_status,
                    "indexed_at": utc_isoformat(doc.indexed_at)
                }
                for doc in documents
            ]
            return {
                "documents": docs_data,
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
    
    async def get_documents_by_type(self, file_type: str) -> List[IndexedDocument]:
        """Get all documents of a specific type"""
        async with AsyncSessionLocal() as session:
            stmt = select(IndexedDocument).where(
                IndexedDocument.file_type == file_type.lower()
            ).order_by(desc(IndexedDocument.indexed_at))
            result = await session.execute(stmt)
            return result.scalars().all()
    
    async def get_recent_documents(self, days: int = 7) -> List[IndexedDocument]:
        """Get documents indexed in the last N days"""
        async with AsyncSessionLocal() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            stmt = select(IndexedDocument).where(
                IndexedDocument.indexed_at >= cutoff_date
            ).order_by(desc(IndexedDocument.indexed_at))
            result = await session.execute(stmt)
            return result.scalars().all()
    
    # NEW: Analytics & Insights Methods
    
    async def get_usage_analytics(self) -> Dict[str, Any]:
        """Get comprehensive usage analytics and insights"""
        async with AsyncSessionLocal() as session:
            total_docs = await session.scalar(select(func.count(IndexedDocument.id)))
            type_breakdown = await session.execute(
                select(
                    IndexedDocument.file_type,
                    func.count(IndexedDocument.id)
                ).group_by(IndexedDocument.file_type)
            )
            status_breakdown = await session.execute(
                select(
                    IndexedDocument.processing_status,
                    func.count(IndexedDocument.id)
                ).group_by(IndexedDocument.processing_status)
            )
            total_sessions = await session.scalar(select(func.count(ChatSession.id)))
            total_messages = await session.scalar(select(func.count(ChatMessage.id)))
            avg_response_time = await session.scalar(
                select(func.avg(ChatMessage.response_time))
            )
            most_used_docs = await session.execute(
                select(
                    IndexedDocument.file_path,
                    func.count(DocumentChatUsage.document_id).label('usage_count')
                ).join(DocumentChatUsage).group_by(IndexedDocument.id).order_by(
                    desc('usage_count')
                ).limit(10)
            )
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
    
    async def get_document_processing_stats(self) -> Dict[str, Any]:
        """Get detailed document processing statistics"""
        async with AsyncSessionLocal() as session:
            processing_stats = await session.execute(
                select(
                    IndexedDocument.processing_status,
                    func.count(IndexedDocument.id),
                    func.avg(func.extract('epoch', IndexedDocument.last_processed - IndexedDocument.indexed_at))
                ).group_by(IndexedDocument.processing_status)
            )
            size_stats = await session.execute(
                select(
                    func.avg(IndexedDocument.file_size),
                    func.min(IndexedDocument.file_size),
                    func.max(IndexedDocument.file_size),
                    func.sum(IndexedDocument.file_size)
                )
            )
            chunk_stats = await session.execute(
                select(
                    func.avg(IndexedDocument.chunks_count),
                    func.min(IndexedDocument.chunks_count),
                    func.max(IndexedDocument.chunks_count),
                    func.sum(IndexedDocument.chunks_count)
                )
            )
            size_row = size_stats.first()
            chunk_row = chunk_stats.first()
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
                    "average_bytes": float(size_row[0]) if size_row and size_row[0] is not None else 0,
                    "min_bytes": size_row[1] if size_row and len(size_row) > 1 and size_row[1] is not None else 0,
                    "max_bytes": size_row[2] if size_row and len(size_row) > 2 and size_row[2] is not None else 0,
                    "total_bytes": size_row[3] if size_row and len(size_row) > 3 and size_row[3] is not None else 0
                },
                "chunk_stats": {
                    "average_chunks": float(chunk_row[0]) if chunk_row and chunk_row[0] is not None else 0,
                    "min_chunks": chunk_row[1] if chunk_row and len(chunk_row) > 1 and chunk_row[1] is not None else 0,
                    "max_chunks": chunk_row[2] if chunk_row and len(chunk_row) > 2 and chunk_row[2] is not None else 0,
                    "total_chunks": chunk_row[3] if chunk_row and len(chunk_row) > 3 and chunk_row[3] is not None else 0
                }
            }
    
    async def get_chat_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get chat-specific analytics for the last N days"""
        async with AsyncSessionLocal() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            daily_messages = await session.execute(
                select(
                    func.date(ChatMessage.timestamp).label('date'),
                    func.count(ChatMessage.id).label('count')
                ).where(
                    ChatMessage.timestamp >= cutoff_date
                ).group_by(
                    func.date(ChatMessage.timestamp)
                ).order_by('date')
            )
            response_time_trends = await session.execute(
                select(
                    func.date(ChatMessage.timestamp).label('date'),
                    func.avg(ChatMessage.response_time).label('avg')
                ).where(
                    ChatMessage.timestamp >= cutoff_date
                ).group_by(
                    func.date(ChatMessage.timestamp)
                ).order_by('date')
            )
            active_directories = await session.execute(
                select(
                    ChatSession.directory_path,
                    func.count(ChatSession.id).label('count')
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
                    {"directory": row.directory_path, "session_count": row.count}
                    for row in active_directories.all()
                ]
            }

    async def get_chat_session_by_id(self, session_id: int) -> Optional[ChatSession]:
        """Get a chat session by its ID"""
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(ChatSession).where(ChatSession.id == session_id)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except Exception as e:
            print(f"Error getting chat session {session_id}: {e}")
            return None