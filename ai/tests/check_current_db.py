"""
Check what's currently in the database for the active directory.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.database import get_db
from database.models import IndexedDocument, ChatSession
from sqlalchemy import select, desc
import logging

logging.basicConfig(level=logging.INFO)

async def check_current_database():
    """Check what documents are in the database for the most recent directory"""
    print("="*80)
    print("CURRENT DATABASE CHECK")
    print("="*80)
    
    async for db_session in get_db():
        # Get the most recent chat session to see what directory is active
        stmt = select(ChatSession).order_by(desc(ChatSession.created_at)).limit(1)
        result = await db_session.execute(stmt)
        recent_session = result.scalar_one_or_none()
        
        if recent_session:
            print(f"\n📁 Most recent directory: {recent_session.directory_path}")
            active_directory = recent_session.directory_path
        else:
            print("\n⚠️  No chat sessions found, checking all documents...")
            active_directory = None
        
        # Get all documents
        stmt = select(IndexedDocument)
        result = await db_session.execute(stmt)
        all_docs = result.scalars().all()
        
        print(f"\n📊 Total documents in database: {len(all_docs)}")
        
        # Filter by directory if we have one
        if active_directory:
            matching_docs = [doc for doc in all_docs if active_directory.lower() in doc.file_path.lower()]
            print(f"📊 Documents matching active directory: {len(matching_docs)}")
            print(f"\n📄 Documents in active directory:")
            for doc in matching_docs:
                print(f"   - {Path(doc.file_path).name}")
                print(f"     Status: {doc.processing_status}, Chunks: {doc.chunks_count}, Type: {doc.file_type}")
        else:
            print(f"\n📄 All documents:")
            for doc in all_docs:
                print(f"   - {Path(doc.file_path).name}")
                print(f"     Status: {doc.processing_status}, Chunks: {doc.chunks_count}, Type: {doc.file_type}")
                print(f"     Path: {doc.file_path}")
        
        # Specifically check for PPTX files
        pptx_docs = [doc for doc in all_docs if doc.file_type == ".pptx"]
        print(f"\n📊 PPTX files in database: {len(pptx_docs)}")
        for doc in pptx_docs:
            print(f"   - {Path(doc.file_path).name}")
            print(f"     Status: {doc.processing_status}")
            print(f"     Chunks: {doc.chunks_count}")
            print(f"     Path: {doc.file_path}")
            if active_directory and active_directory.lower() not in doc.file_path.lower():
                print(f"     ⚠️  WARNING: This file is NOT in the active directory!")
        
        break

if __name__ == "__main__":
    asyncio.run(check_current_database())

