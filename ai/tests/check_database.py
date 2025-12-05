"""
Check what PPTX files are actually in the database.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.database import get_db
from database.models import IndexedDocument
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO)

async def check_database():
    """Check what documents are in the database"""
    print("="*80)
    print("DATABASE DOCUMENT CHECK")
    print("="*80)
    
    async for db_session in get_db():
        # Get all documents
        stmt = select(IndexedDocument)
        result = await db_session.execute(stmt)
        all_docs = result.scalars().all()
        
        print(f"\n📊 Total documents in database: {len(all_docs)}")
        
        # Filter PPTX files
        pptx_docs = [doc for doc in all_docs if doc.file_type == ".pptx"]
        print(f"📊 PPTX documents: {len(pptx_docs)}")
        
        print("\n" + "-"*80)
        print("ALL DOCUMENTS:")
        print("-"*80)
        for doc in all_docs:
            print(f"\n📄 {Path(doc.file_path).name}")
            print(f"   Type: {doc.file_type}")
            print(f"   Status: {doc.processing_status}")
            print(f"   Chunks: {doc.chunks_count}")
            print(f"   Size: {doc.file_size / 1024:.2f} KB" if doc.file_size else "   Size: Unknown")
            print(f"   Path: {doc.file_path}")
        
        if pptx_docs:
            print("\n" + "-"*80)
            print("PPTX DOCUMENTS DETAILS:")
            print("-"*80)
            for doc in pptx_docs:
                print(f"\n📄 {Path(doc.file_path).name}")
                print(f"   Status: {doc.processing_status}")
                print(f"   Chunks: {doc.chunks_count}")
                print(f"   Preview: {doc.content_preview[:100] if doc.content_preview else 'None'}...")
                print(f"   Hash: {doc.file_hash[:20] if doc.file_hash else 'None'}...")
        
        break

if __name__ == "__main__":
    asyncio.run(check_database())

