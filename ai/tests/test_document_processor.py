import asyncio
import sys
import os
import tempfile
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor import DocumentProcessor

async def test_document_processor():
    print("🧪 Testing document processor...")
    
    # Create a temporary directory with test files
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"📁 Test directory: {temp_dir}")
        
        # Create test files
        test_files = {
            "test.txt": "This is a test document with some content.",
            "large.txt": "x" * (51 * 1024 * 1024),  # 51MB file (should be rejected)
            "test.docx": None,  # Will create a simple docx
            "corrupted.pdf": b"not a pdf file"  # Corrupted file
        }
        
        # Create text files
        for filename, content in test_files.items():
            if content and isinstance(content, str):
                file_path = os.path.join(temp_dir, filename)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"�� Created: {filename}")
        
        # Test document processor
        processor = DocumentProcessor()
        
        try:
            # Initialize from directory
            await processor.initialize_from_directory(temp_dir)
            
            # Get stats
            stats = processor.get_index_stats()
            print(f"📊 Index stats: {stats}")
            
            # Test query
            if processor.query_engine:
                response = await processor.query("What is this document about?")
                print(f"🤖 Query response: {response}")
            
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_document_processor()) 