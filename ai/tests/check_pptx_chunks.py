"""
Check how many chunks were created for the PPTX file and what content they contain.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.database import get_db
from database.models import IndexedDocument
from sqlalchemy import select
from services.document_processor.vector_store import VectorStoreService
import logging

logging.basicConfig(level=logging.INFO)

async def check_chunks():
    """Check chunks for PPTX files"""
    print("="*80)
    print("PPTX CHUNKS CHECK")
    print("="*80)
    
    vector_store = VectorStoreService(persist_dir="./chroma_db")
    # Initialize client synchronously
    vector_store._initialize_client()
    
    async for db_session in get_db():
        stmt = select(IndexedDocument).where(
            IndexedDocument.file_type == ".pptx"
        )
        result = await db_session.execute(stmt)
        pptx_docs = result.scalars().all()
        
        for doc in pptx_docs:
            filename = Path(doc.file_path).name
            print(f"\n{'='*80}")
            print(f"File: {filename}")
            print(f"{'='*80}")
            print(f"Status: {doc.processing_status}")
            print(f"Chunks in DB: {doc.chunks_count}")
            print(f"Preview length: {len(doc.content_preview) if doc.content_preview else 0}")
            
            # Get chunks from vector store
            try:
                chunks_result = vector_store.collection.get(
                    where={"file_path": doc.file_path}
                )
                
                if chunks_result and chunks_result.get('ids'):
                    chunk_ids = chunks_result['ids']
                    chunk_texts = chunks_result.get('documents', [])
                    chunk_metadatas = chunks_result.get('metadatas', [])
                    
                    print(f"\nChunks in vector store: {len(chunk_ids)}")
                    
                    for i, (chunk_id, chunk_text, metadata) in enumerate(zip(chunk_ids, chunk_texts, chunk_metadatas), 1):
                        print(f"\n--- Chunk {i} (ID: {chunk_id}) ---")
                        print(f"Length: {len(chunk_text)} characters")
                        print(f"Metadata: {metadata}")
                        print(f"Preview (first 300 chars):")
                        print(chunk_text[:300])
                        if len(chunk_text) > 300:
                            print("...")
                        print(f"Last 100 chars:")
                        print(chunk_text[-100:])
                else:
                    print("\n⚠️  No chunks found in vector store!")
                    
            except Exception as e:
                print(f"\n❌ Error getting chunks: {e}")
                import traceback
                traceback.print_exc()
        
        break

if __name__ == "__main__":
    asyncio.run(check_chunks())

