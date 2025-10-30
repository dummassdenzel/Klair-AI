"""
Test if TCO005 content is being retrieved correctly
"""
import asyncio
import sys
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, str(Path(__file__).parent))

from services.document_processor import DocumentProcessorOrchestrator
from dotenv import load_dotenv
import os

load_dotenv()

async def test_retrieval():
    """Test retrieval of TCO005 content"""
    print("=" * 70)
    print("TCO005 RETRIEVAL TEST")
    print("=" * 70)
    
    try:
        orchestrator = DocumentProcessorOrchestrator(
            llm_provider=os.getenv("LLM_PROVIDER", "gemini"),
            gemini_api_key=os.getenv("GEMINI_API_KEY")
        )
        
        # Test query
        query = "What is the G.P# of TCO005?"
        print(f"\nQuery: {query}\n")
        
        result = await orchestrator.query(query)
        
        print(f"\nResponse: {result.message}")
        print(f"\nSources ({len(result.sources)}):")
        for i, source in enumerate(result.sources, 1):
            print(f"  {i}. {Path(source['file_path']).name} - {source['relevance_score']}")
            print(f"     Preview: {source['content_snippet'][:100]}...")
        
        print(f"\nResponse time: {result.response_time}s")
        
        # Check if content was actually retrieved
        if result.sources:
            has_tco005 = any('TCO005' in source['file_path'] for source in result.sources)
            print(f"\n✅ TCO005 in sources: {has_tco005}")
            
            if has_tco005:
                tco005_source = next(s for s in result.sources if 'TCO005' in s['file_path'])
                print(f"   Chunks found: {tco005_source.get('chunks_found', 0)}")
                print(f"   Content length: {len(tco005_source.get('content_snippet', ''))}")
        else:
            print("\n❌ No sources returned!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_retrieval())

