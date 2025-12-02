import asyncio
import sys
import os
import tempfile
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.file_monitor import FileMonitorService
from services.document_processor import DocumentProcessorOrchestrator

async def test_new_file_monitor():
    """Test the new FileMonitorService"""
    print("🧪 Testing new FileMonitorService...")
    
    # Create test directory
    test_dir = tempfile.mkdtemp(prefix="test_monitor_v2_")
    print(f"📁 Test directory: {test_dir}")
    
    try:
        # Initialize document processor
        processor = DocumentProcessorOrchestrator(persist_dir="./test_monitor_v2_db")
        
        # Create file monitor service
        monitor = FileMonitorService(processor)
        
        # Start monitoring
        await monitor.start_monitoring(test_dir)
        
        # Test file creation
        test_file = os.path.join(test_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("Test content")
        
        # Wait for processing
        await asyncio.sleep(3)
        
        # Test file modification
        with open(test_file, "a") as f:
            f.write("\nModified content")
        
        # Wait for processing
        await asyncio.sleep(3)
        
        # Test file deletion
        os.remove(test_file)
        
        # Wait for processing
        await asyncio.sleep(3)
        
        # Stop monitoring
        await monitor.stop_monitoring()
        
        print("✅ New file monitor test completed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        # Cleanup
        import shutil
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        if os.path.exists("./test_monitor_v2_db"):
            shutil.rmtree("./test_monitor_v2_db")

if __name__ == "__main__":
    asyncio.run(test_new_file_monitor())