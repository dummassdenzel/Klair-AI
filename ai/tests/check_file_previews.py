"""
Check the content previews for all files to see if one is empty.
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

async def check_previews():
    """Check content previews for all documents"""
    print("="*80)
    print("CONTENT PREVIEW CHECK")
    print("="*80)
    
    async for db_session in get_db():
        stmt = select(IndexedDocument)
        result = await db_session.execute(stmt)
        all_docs = result.scalars().all()
        
        print(f"\nTotal documents: {len(all_docs)}\n")
        
        for doc in all_docs:
            filename = Path(doc.file_path).name
            print(f"File: {filename}")
            print(f"  Status: {doc.processing_status}")
            print(f"  Chunks: {doc.chunks_count}")
            print(f"  Preview length: {len(doc.content_preview) if doc.content_preview else 0}")
            if doc.content_preview:
                print(f"  Preview (first 200 chars): {doc.content_preview[:200]}...")
            else:
                print(f"  Preview: EMPTY OR NONE")
            print()
        
        break

if __name__ == "__main__":
    asyncio.run(check_previews())

