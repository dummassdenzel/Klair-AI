import asyncio
import sys
import os
import tempfile
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor import DocumentProcessor
from services.file_monitor import DocumentFileHandler
from watchdog.observers import Observer

async def test_integration():
    """Test the integration between components"""
    print("🧪 Testing component integration...")
    
    # Create test directory
    test_dir = tempfile.mkdtemp(prefix="test_integration_")
    print(f"📁 Test directory: {test_dir}")
    
    try:
        # Create test file
        test_file = os.path.join(test_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("This is a test document for integration testing.")
        
        # Initialize document processor
        processor = DocumentProcessor(persist_dir="./test_integration_db")
        await processor.initialize_from_directory(test_dir)
        
        # Test query
        response = await processor.query("What is this document about?")
        print(f"🤖 Query response: {response.message}")
        
        # Test file monitoring
        changes_detected = []
        
        async def on_file_change(file_path: str, is_deletion: bool = False):
            changes_detected.append((file_path, is_deletion))
            print(f"🔄 File change detected: {file_path} (deletion: {is_deletion})")
        
        handler = DocumentFileHandler(on_file_change)
        handler.set_event_loop(asyncio.get_running_loop())
        
        observer = Observer()
        observer.schedule(handler, test_dir, recursive=False)
        observer.start()
        
        # Test file modification
        with open(test_file, "a") as f:
            f.write("\nAdditional content for testing.")
        
        # Wait for processing
        await asyncio.sleep(5)
        
        # Test query after modification
        response2 = await processor.query("What additional content was added?")
        print(f"🤖 Query after modification: {response2.message}")
        
        # Cleanup
        handler.cleanup()
        observer.stop()
        observer.join()
        
        print("✅ Integration test completed successfully!")
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
    finally:
        # Cleanup
        import shutil
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        if os.path.exists("./test_integration_db"):
            shutil.rmtree("./test_integration_db")

if __name__ == "__main__":
    asyncio.run(test_integration())