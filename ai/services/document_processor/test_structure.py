"""
Simple test to verify the new modular structure works correctly.
This is not a comprehensive test suite, just a structure verification.
"""

import asyncio
import sys
from pathlib import Path

# Add the parent directory to the path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

async def test_imports():
    """Test that all services can be imported correctly"""
    try:
        print("Testing imports...")
        
        # Test importing the main orchestrator
        from services.document_processor import DocumentProcessorOrchestrator
        print("✓ DocumentProcessorOrchestrator imported successfully")
        
        # Test importing individual services
        from services.document_processor import TextExtractor
        print("✓ TextExtractor imported successfully")
        
        from services.document_processor import DocumentChunker
        print("✓ DocumentChunker imported successfully")
        
        from services.document_processor import EmbeddingService
        print("✓ EmbeddingService imported successfully")
        
        from services.document_processor import VectorStoreService
        print("✓ VectorStoreService imported successfully")
        
        from services.document_processor import LLMService
        print("✓ LLMService imported successfully")
        
        from services.document_processor import FileValidator
        print("✓ FileValidator imported successfully")
        
        # Test importing models
        from services.document_processor import DocumentChunk, QueryResult, FileMetadata
        print("✓ Models imported successfully")
        
        # Test importing configuration
        from services.document_processor import config
        print("✓ Configuration imported successfully")
        
        print("\n🎉 All imports successful! The new structure is working correctly.")
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False
    
    return True

async def test_service_initialization():
    """Test that services can be initialized without errors"""
    try:
        print("\nTesting service initialization...")
        
        from services.document_processor import DocumentProcessorOrchestrator
        
        # Test initialization with minimal config
        processor = DocumentProcessorOrchestrator(
            persist_dir="./test_chroma_db",
            embed_model_name="BAAI/bge-small-en-v1.5",
            chunk_size=1000,
            chunk_overlap=200
        )
        print("✓ DocumentProcessorOrchestrator initialized successfully")
        
        # Test cleanup
        await processor.cleanup()
        print("✓ Cleanup completed successfully")
        
        print("🎉 Service initialization test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Service initialization failed: {e}")
        return False

async def main():
    """Run all tests"""
    print("🧪 Testing Document Processor Service Structure\n")
    
    # Test imports
    imports_ok = await test_imports()
    if not imports_ok:
        print("\n❌ Import tests failed. Check the structure.")
        return
    
    # Test service initialization
    init_ok = await test_service_initialization()
    if not init_ok:
        print("\n❌ Service initialization tests failed.")
        return
    
    print("\n🎉 All tests passed! The refactored structure is working correctly.")

if __name__ == "__main__":
    asyncio.run(main())
