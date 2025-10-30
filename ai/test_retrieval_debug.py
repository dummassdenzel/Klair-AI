"""
Debug document retrieval to find where it's failing
"""
import asyncio
import sys
from pathlib import Path
import logging

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, str(Path(__file__).parent))

from services.document_processor import DocumentProcessorOrchestrator
from dotenv import load_dotenv
import os

load_dotenv()

async def debug_retrieval():
    """Debug why content is not being retrieved"""
    print("=" * 70)
    print("RETRIEVAL DEBUG TEST")
    print("=" * 70)
    
    try:
        orchestrator = DocumentProcessorOrchestrator(
            llm_provider=os.getenv("LLM_PROVIDER", "gemini"),
            gemini_api_key=os.getenv("GEMINI_API_KEY")
        )
        
        # Test 1: Check if documents are indexed
        print("\n1. Checking indexed documents...")
        print(f"   File metadata count: {len(orchestrator.file_metadata)}")
        for file_path in list(orchestrator.file_metadata.keys())[:3]:
            print(f"   - {Path(file_path).name}")
        
        # Test 2: Check vector store
        print("\n2. Checking vector store...")
        stats = await orchestrator.get_stats()
        print(f"   Total chunks in vector store: {stats.get('total_chunks', 0)}")
        
        # Test 3: Check BM25 index
        print("\n3. Checking BM25 index...")
        bm25_stats = orchestrator.bm25_service.get_stats()
        print(f"   BM25 document count: {bm25_stats['document_count']}")
        print(f"   BM25 index built: {bm25_stats['index_built']}")
        
        # Test 4: Test semantic search directly
        print("\n4. Testing semantic search for 'TCO005'...")
        query_embedding = orchestrator.embedding_service.encode_single_text("What is in TCO005?")
        semantic_results = await orchestrator.vector_store.search_similar(query_embedding, 15)
        
        if semantic_results and semantic_results['documents'] and semantic_results['documents'][0]:
            print(f"   Semantic results found: {len(semantic_results['documents'][0])}")
            # Check if any contain TCO005
            tco005_chunks = [
                meta for meta in semantic_results['metadatas'][0]
                if 'TCO005' in meta.get('file_path', '')
            ]
            print(f"   TCO005 chunks in semantic results: {len(tco005_chunks)}")
        else:
            print("   ❌ NO semantic results found!")
        
        # Test 5: Test BM25 search directly
        print("\n5. Testing BM25 search for 'G.P#'...")
        bm25_results = orchestrator.bm25_service.search("G.P#", top_k=15)
        print(f"   BM25 results found: {len(bm25_results)}")
        if bm25_results:
            for doc_id, score, metadata in bm25_results[:3]:
                print(f"   - {Path(metadata.get('file_path', 'unknown')).name}: score={score:.2f}")
        
        # Test 6: Test full query
        print("\n6. Testing full query: 'What is the G.P# of TCO005?'...")
        result = await orchestrator.query("What is the G.P# of TCO005?")
        print(f"   Sources returned: {len(result.sources)}")
        if result.sources:
            for source in result.sources:
                print(f"   - {Path(source['file_path']).name}: {source['relevance_score']}")
        else:
            print("   ❌ NO sources returned!")
        
        print(f"\n   Response preview: {result.message[:200]}...")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_retrieval())

