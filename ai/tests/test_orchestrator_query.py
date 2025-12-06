"""
Test the orchestrator query method directly to see what it returns.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.document_processor import DocumentProcessorOrchestrator
from config import settings
import logging

logging.basicConfig(level=logging.INFO)

async def test_query(question: str, orchestrator: DocumentProcessorOrchestrator):
    """Test a query directly on the orchestrator"""
    print("\n" + "="*80)
    print(f"QUERY: {question}")
    print("="*80)
    
    try:
        result = await orchestrator.query(question)
        
        print(f"\n✅ Query completed!")
        print(f"📝 Response: {result.message[:500]}...")
        print(f"📊 Sources: {len(result.sources)} documents")
        print(f"📊 Retrieval count: {result.retrieval_count}")
        print(f"📊 Query type: {result.query_type}")
        
        if result.sources:
            print(f"\n📄 Sources found:")
            for i, source in enumerate(result.sources, 1):
                filename = Path(source.get('file_path', '')).name
                print(f"   {i}. {filename}")
                print(f"      - Status: {source.get('processing_status', 'unknown')}")
                print(f"      - Chunks: {source.get('chunks_found', 0)}")
                print(f"      - Type: {source.get('file_type', 'unknown')}")
        else:
            print("\n⚠️  No sources returned!")
            
    except Exception as e:
        print(f"\n❌ Query failed: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Test queries directly on orchestrator"""
    print("="*80)
    print("ORCHESTRATOR DIRECT QUERY TEST")
    print("="*80)
    
    # Initialize orchestrator (same config as main.py)
    orchestrator = DocumentProcessorOrchestrator(
        persist_dir="./chroma_db",
        embed_model_name="BAAI/bge-small-en-v1.5",
        max_file_size_mb=50,
        chunk_size=1000,
        chunk_overlap=200,
        ollama_base_url="http://localhost:11434",
        ollama_model="tinyllama",
        gemini_api_key=settings.GEMINI_API_KEY,
        gemini_model=settings.GEMINI_MODEL,
        llm_provider=settings.LLM_PROVIDER
    )
    
    # The directory should already be initialized by the server
    # But we can check if it needs initialization
    print("\n⚠️  Note: This test assumes the server has already initialized a directory")
    print("⚠️  The orchestrator will use the existing ChromaDB and database")
    
    questions = [
        "What do you know about our files?",
        "What do you know about Lazt Bean Cafe?",
        "What do you know about Copy of PJTC Speaker Pubmat?"
    ]
    
    for question in questions:
        await test_query(question, orchestrator)
        print("\n" + "-"*80)
    
    print("\n" + "="*80)
    print("ALL TESTS COMPLETE")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())

