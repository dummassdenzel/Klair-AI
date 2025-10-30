"""
Test document indexing with detailed logging
"""
import asyncio
import sys
from pathlib import Path
import logging

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, str(Path(__file__).parent))

from services.document_processor import DocumentProcessorOrchestrator
from dotenv import load_dotenv
import os

load_dotenv()

async def test_indexing():
    """Test document indexing"""
    print("=" * 70)
    print("DOCUMENT INDEXING TEST")
    print("=" * 70)
    
    try:
        # Initialize orchestrator
        print("\n1. Initializing orchestrator...")
        orchestrator = DocumentProcessorOrchestrator(
            persist_dir="./test_indexing_db",
            llm_provider=os.getenv("LLM_PROVIDER", "gemini"),
            gemini_api_key=os.getenv("GEMINI_API_KEY")
        )
        print("✅ Orchestrator initialized")
        
        # Clear old data
        print("\n2. Clearing old data...")
        await orchestrator.clear_all_data()
        print("✅ Old data cleared")
        
        # Get documents directory
        docs_dir = input("\n3. Enter path to documents directory: ").strip()
        if not docs_dir:
            docs_dir = "C:\\xampp\\htdocs\\klair-ai\\documents"
            print(f"   Using default: {docs_dir}")
        
        docs_path = Path(docs_dir)
        if not docs_path.exists():
            print(f"❌ Directory does not exist: {docs_dir}")
            return
        
        # Count files
        supported_files = []
        for file_path in docs_path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in ['.pdf', '.txt', '.docx']:
                supported_files.append(str(file_path))
        
        print(f"\n4. Found {len(supported_files)} supported files:")
        for f in supported_files[:5]:
            print(f"   - {Path(f).name}")
        if len(supported_files) > 5:
            print(f"   ... and {len(supported_files) - 5} more")
        
        # Test indexing first file
        if supported_files:
            test_file = supported_files[0]
            print(f"\n5. Testing indexing of: {Path(test_file).name}")
            
            try:
                await orchestrator.add_document(test_file)
                print("✅ Document indexed successfully")
                
                # Check stats
                print("\n6. Checking index stats:")
                vector_stats = await orchestrator.get_stats()
                print(f"   Vector store: {vector_stats.get('total_chunks', 0)} chunks")
                
                bm25_stats = orchestrator.bm25_service.get_stats()
                print(f"   BM25 index: {bm25_stats['document_count']} documents")
                print(f"   BM25 built: {bm25_stats['index_built']}")
                
            except Exception as e:
                print(f"❌ Error indexing document: {e}")
                import traceback
                traceback.print_exc()
        
        # Clean up
        await orchestrator.clear_all_data()
        print("\n✅ TEST COMPLETE")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_indexing())

