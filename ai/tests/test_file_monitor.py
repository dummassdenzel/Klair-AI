import asyncio
import sys
import os
import tempfile
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.file_monitor import DocumentFileHandler
from watchdog.observers import Observer

class TestFileMonitor:
    def __init__(self):
        self.test_dir = None
        self.handler = None
        self.observer = None
        self.changes_detected = []
    
    async def setup(self):
        """Set up test environment"""
        print("🧪 Setting up file monitor test environment...")
        
        # Create temporary directory
        self.test_dir = tempfile.mkdtemp(prefix="test_monitor_")
        print(f"📁 Test directory: {self.test_dir}")
        
        # Create file handler
        async def on_file_change(file_path: str, is_deletion: bool = False):
            self.changes_detected.append((file_path, is_deletion))
            print(f"🔄 File change detected: {file_path} (deletion: {is_deletion})")
        
        self.handler = DocumentFileHandler(on_file_change)
        self.handler.set_event_loop(asyncio.get_running_loop())
        
        # Start the observer
        self.observer = Observer()
        self.observer.schedule(self.handler, self.test_dir, recursive=False)
        self.observer.start()
        print(f"👁️ Observer started for: {self.test_dir}")
        
        print("✅ File monitor test environment ready")
    
    async def test_file_creation(self):
        """Test file creation detection"""
        print("\n🔍 Testing file creation detection...")
        
        # Clear previous events
        self.changes_detected.clear()
        
        # Create a test file
        test_file = os.path.join(self.test_dir, "test_creation.txt")
        with open(test_file, "w") as f:
            f.write("Test content")
        
        # Wait for detection
        await asyncio.sleep(5)  # Increased wait time
        
        # Check if detected
        creation_events = [event for event in self.changes_detected if not event[1] and test_file in event[0]]
        print(f"📊 Creation events detected: {len(creation_events)}")
        print(f"📋 All events: {self.changes_detected}")
        
        assert len(creation_events) > 0, "File creation should be detected"
        
        print("✅ File creation test passed")
        return True
    
    async def test_file_modification(self):
        """Test file modification detection"""
        print("\n🔍 Testing file modification detection...")
        
        # Clear previous events
        self.changes_detected.clear()
        
        # Create and modify a file
        test_file = os.path.join(self.test_dir, "test_modification.txt")
        with open(test_file, "w") as f:
            f.write("Initial content")
        
        # Wait a bit
        await asyncio.sleep(2)
        
        # Modify the file
        with open(test_file, "a") as f:
            f.write("\nModified content")
        
        # Wait for detection
        await asyncio.sleep(5)
        
        # Check if detected
        modification_events = [event for event in self.changes_detected if not event[1] and test_file in event[0]]
        print(f"📊 Modification events detected: {len(modification_events)}")
        
        assert len(modification_events) > 0, "File modification should be detected"
        
        print("✅ File modification test passed")
        return True
    
    async def test_file_deletion(self):
        """Test file deletion detection"""
        print("\n🔍 Testing file deletion detection...")
        
        # Clear previous events
        self.changes_detected.clear()
        
        # Create a file
        test_file = os.path.join(self.test_dir, "test_deletion.txt")
        with open(test_file, "w") as f:
            f.write("Test content")
        
        # Wait a bit
        await asyncio.sleep(2)
        
        # Delete the file
        os.remove(test_file)
        
        # Wait for detection
        await asyncio.sleep(5)
        
        # Check if detected
        deletion_events = [event for event in self.changes_detected if event[1] and test_file in event[0]]
        print(f"📊 Deletion events detected: {len(deletion_events)}")
        
        assert len(deletion_events) > 0, "File deletion should be detected"
        
        print("✅ File deletion test passed")
        return True
    
    async def test_unsupported_files(self):
        """Test that unsupported files are ignored"""
        print("\n🔍 Testing unsupported file filtering...")
        
        # Clear previous events
        self.changes_detected.clear()
        
        # Create unsupported file
        unsupported_file = os.path.join(self.test_dir, "test.xyz")
        with open(unsupported_file, "w") as f:
            f.write("Unsupported content")
        
        # Wait for detection
        await asyncio.sleep(3)
        
        # Check that it was NOT detected
        unsupported_events = [event for event in self.changes_detected if unsupported_file in event[0]]
        print(f"�� Unsupported events detected: {len(unsupported_events)} (should be 0)")
        
        assert len(unsupported_events) == 0, "Unsupported files should be ignored"
        
        print("✅ Unsupported file filtering test passed")
        return True
    
    async def test_debouncing(self):
        """Test debouncing functionality"""
        print("\n🧪 Testing debouncing...")
        
        # Clear previous events
        self.changes_detected.clear()
        
        test_file = os.path.join(self.test_dir, "test_debounce.txt")
        
        # Create file
        with open(test_file, "w") as f:
            f.write("Initial content")
        
        # Wait for initial creation
        await asyncio.sleep(3)
        
        # Rapidly modify the file
        for i in range(5):
            with open(test_file, "w") as f:
                f.write(f"Content {i}")
            await asyncio.sleep(0.1)  # Very rapid changes
        
        # Wait for debouncing
        await asyncio.sleep(7)  # Increased wait time for debouncing
        
        # Should have fewer events than modifications due to debouncing
        debounce_events = [event for event in self.changes_detected if test_file in event[0]]
        print(f"📊 Events detected: {len(debounce_events)} (should be less than 5 due to debouncing)")
        
        assert len(debounce_events) > 0, "At least one event should be detected"
        assert len(debounce_events) < 5, "Debouncing should reduce the number of events"
        
        print("✅ Debouncing test passed")
        return True
    
    async def cleanup(self):
        """Clean up test environment"""
        print("\n🧹 Cleaning up file monitor test environment...")
        
        # Stop the observer
        if self.observer:
            self.observer.stop()
            self.observer.join()
            print("🛑 Observer stopped")
        
        # Clean up handler
        if self.handler:
            self.handler.cleanup()
            print("🧹 Handler cleaned up")
        
        if self.test_dir and os.path.exists(self.test_dir):
            import shutil
            shutil.rmtree(self.test_dir)
            print(f"🗑️ Removed test directory: {self.test_dir}")
        
        print("✅ Cleanup completed")

async def run_file_monitor_tests():
    """Run all file monitor tests"""
    print("🚀 Starting File Monitor Tests...")
    
    tester = TestFileMonitor()
    
    try:
        # Setup
        await tester.setup()
        
        # Run tests
        tests = [
            ("File Creation", tester.test_file_creation),
            ("File Modification", tester.test_file_modification),
            ("File Deletion", tester.test_file_deletion),
            ("Unsupported Files", tester.test_unsupported_files),
            ("Debouncing", tester.test_debouncing),
        ]
        
        passed = 0
        total = len(tests)
        
        for test_name, test_func in tests:
            print(f"\n{'='*50}")
            print(f"🧪 Running: {test_name}")
            print(f"{'='*50}")
            
            try:
                result = await test_func()
                if result:
                    passed += 1
                    print(f"✅ {test_name}: PASSED")
                else:
                    print(f"❌ {test_name}: FAILED")
            except Exception as e:
                print(f"❌ {test_name}: ERROR - {e}")
        
        # Summary
        print(f"\n{'='*50}")
        print(f"📊 TEST SUMMARY")
        print(f"{'='*50}")
        print(f"✅ Passed: {passed}/{total}")
        print(f"❌ Failed: {total - passed}/{total}")
        print(f"📈 Success Rate: {(passed/total)*100:.1f}%")
        
        if passed == total:
            print("🎉 All file monitor tests passed!")
        else:
            print("⚠️ Some tests failed. Check the output above.")
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
    
    finally:
        # Cleanup
        await tester.cleanup()

if __name__ == "__main__":
    asyncio.run(run_file_monitor_tests())