import asyncio
import sys
import os
import tempfile
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor import DocumentProcessor
from services.file_monitor import FileMonitorService  # Updated import

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
        
        # Test initial query
        response = await processor.query("What is this document about?")
        print(f"🤖 Initial query response: {response.message}")
        print(f"📋 Sources found: {len(response.sources)}")
        
        # Initialize file monitor service
        file_monitor = FileMonitorService(processor)
        await file_monitor.start_monitoring(test_dir)
        
        print("📝 File monitoring started...")
        
        # Test file modification
        print("📝 Modifying test file...")
        with open(test_file, "a") as f:
            f.write("\nAdditional content for testing.")
        
        # Wait for processing (give more time for debouncing)
        print("⏳ Waiting for file processing...")
        await asyncio.sleep(3)
        
        # Test query after modification
        response2 = await processor.query("What additional content was added?")
        print(f"🤖 Query after modification: {response2.message}")
        print(f"📋 Sources found: {len(response2.sources)}")
        
        # Test file deletion
        print("🗑️ Testing file deletion...")
        os.remove(test_file)
        
        # Wait for processing
        await asyncio.sleep(2)
        
        # Test query after deletion
        response3 = await processor.query("What is this document about?")
        print(f"🤖 Query after deletion: {response3.message}")
        
        # Stop file monitoring
        await file_monitor.stop_monitoring()
        
        # Clean up processor
        await processor.cleanup()
        
        print("✅ Integration test completed successfully!")
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        import shutil
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        if os.path.exists("./test_integration_db"):
            try:
                shutil.rmtree("./test_integration_db")
            except Exception as e:
                print(f"⚠️ Could not remove test DB (normal): {e}")

async def test_full_workflow():
    """Test the complete workflow including multiple file operations"""
    print("\n🧪 Testing full workflow...")
    
    test_dir = tempfile.mkdtemp(prefix="test_workflow_")
    print(f"📁 Workflow test directory: {test_dir}")
    
    try:
        # Initialize processor
        processor = DocumentProcessor(persist_dir="./test_workflow_db")
        
        # Create multiple files
        files = {
            "sales.txt": "Total Revenue: ₱50,000\nProducts: 100 units",
            "inventory.txt": "Current stock: 500 items\nLow stock alert: 50 items",
            "customers.txt": "Active customers: 250\nNew customers this month: 25"
        }
        
        for filename, content in files.items():
            with open(os.path.join(test_dir, filename), "w") as f:
                f.write(content)
        
        # Initialize from directory
        await processor.initialize_from_directory(test_dir)
        
        # Start monitoring
        file_monitor = FileMonitorService(processor)
        await file_monitor.start_monitoring(test_dir)
        
        # Test queries
        queries = [
            "What is the total revenue?",
            "How many items are in stock?",
            "How many customers are there?"
        ]
        
        for query in queries:
            response = await processor.query(query)
            print(f"🤖 Query: {query}")
            print(f"📝 Response: {response.message}")
            print(f"📋 Sources: {len(response.sources)}")
            print("---")
        
        # Test file updates
        print("📝 Testing file updates...")
        with open(os.path.join(test_dir, "sales.txt"), "a") as f:
            f.write("\nUpdated revenue: ₱75,000")
        
        await asyncio.sleep(3)
        
        # Test updated query
        response = await processor.query("What is the updated revenue?")
        print(f"🤖 Updated query response: {response.message}")
        
        # Cleanup
        await file_monitor.stop_monitoring()
        await processor.cleanup()
        
        print("✅ Full workflow test completed!")
        
    except Exception as e:
        print(f"❌ Workflow test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        import shutil
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        if os.path.exists("./test_workflow_db"):
            try:
                shutil.rmtree("./test_workflow_db")
            except Exception as e:
                print(f"⚠️ Could not remove workflow test DB: {e}")

async def run_all_integration_tests():
    """Run all integration tests"""
    print("🚀 Starting Integration Tests...")
    
    tests = [
        ("Basic Integration", test_integration),
        ("Full Workflow", test_full_workflow),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*60}")
        print(f"🧪 Running: {test_name}")
        print(f"{'='*60}")
        
        try:
            await test_func()
            passed += 1
            print(f"✅ {test_name}: PASSED")
        except Exception as e:
            print(f"❌ {test_name}: FAILED - {e}")
    
    print(f"\n{'='*60}")
    print(f"📊 INTEGRATION TEST SUMMARY")
    print(f"{'='*60}")
    print(f"✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")
    print(f"📈 Success Rate: {(passed/total)*100:.1f}%")
    
    if passed == total:
        print("🎉 All integration tests passed!")
    else:
        print("⚠️ Some integration tests failed.")

if __name__ == "__main__":
    asyncio.run(run_all_integration_tests())