import asyncio
import sys
import os
import tempfile
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.file_monitor import DocumentFileHandler

async def test_file_monitor():
    print("🧪 Testing file monitor...")
    
    # Create a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"📁 Monitoring directory: {temp_dir}")
        
        # Track file changes
        changes = []
        
        async def on_file_change(file_path: str, is_deletion: bool = False):
            changes.append((file_path, is_deletion))
            print(f"📝 File change detected: {file_path} (deletion: {is_deletion})")
        
        # Create file handler
        handler = DocumentFileHandler(on_file_change)
        handler.set_event_loop(asyncio.get_running_loop())
        
        # Create observer
        from watchdog.observers import Observer
        observer = Observer()
        observer.schedule(handler, temp_dir, recursive=False)
        observer.start()
        
        try:
            # Test file creation
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, 'w') as f:
                f.write("test content")
            
            # Wait for debounce
            await asyncio.sleep(3)
            
            # Test file modification
            with open(test_file, 'a') as f:
                f.write("\nmore content")
            
            # Wait for debounce
            await asyncio.sleep(3)
            
            # Test file deletion
            os.remove(test_file)
            
            # Wait for debounce
            await asyncio.sleep(3)
            
            print(f"📊 Total changes detected: {len(changes)}")
            for file_path, is_deletion in changes:
                print(f"  - {file_path} (deletion: {is_deletion})")
            
        finally:
            observer.stop()
            observer.join()
            handler.cleanup()

if __name__ == "__main__":
    asyncio.run(test_file_monitor())