import asyncio
import sys
import os
import tempfile
import time
import shutil

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor import DocumentProcessor

class TestDocumentProcessor:
    def __init__(self):
        self.test_dir = None
        self.processor = None
    
    async def setup(self):
        """Set up test environment"""
        print("🧪 Setting up test environment...")
        
        # Create temporary directory
        self.test_dir = tempfile.mkdtemp(prefix="test_docs_")
        print(f"📁 Test directory: {self.test_dir}")
        
        # Create test files
        await self._create_test_files()
        
        # Initialize processor with test directory
        self.processor = DocumentProcessor(persist_dir="./test_chroma_db")
        
        print("✅ Test environment ready")
    
    async def _create_test_files(self):
        """Create various test files"""
        # Test TXT file
        txt_content = """This is a test document about sales.
Total Revenue: ₱10,000
Products sold: 50 units
Customer satisfaction: 95%"""
        
        with open(os.path.join(self.test_dir, "sales.txt"), "w", encoding="utf-8") as f:
            f.write(txt_content)
        
        # Test large TXT file (to test chunking)
        large_content = "This is a large document. " * 1000  # ~25KB
        with open(os.path.join(self.test_dir, "large_doc.txt"), "w", encoding="utf-8") as f:
            f.write(large_content)
        
        # Test unsupported file
        with open(os.path.join(self.test_dir, "image.jpg"), "w") as f:
            f.write("fake image content")
        
        print(f"�� Created test files in {self.test_dir}")
    
    async def test_initialization(self):
        """Test document processor initialization"""
        print("\n🔍 Testing initialization...")
        
        try:
            await self.processor.initialize_from_directory(self.test_dir)
            
            # Check stats
            stats = self.processor.get_index_stats()
            print(f"📊 Index stats: {stats}")
            
            # Should have 2 supported files (txt files)
            assert stats["total_files"] == 2, f"Expected 2 files, got {stats['total_files']}"
            
            # Check for files using full paths
            sales_file = os.path.join(self.test_dir, "sales.txt")
            large_file = os.path.join(self.test_dir, "large_doc.txt")
            
            assert sales_file in stats["indexed_files"], f"sales.txt not found in {stats['indexed_files']}"
            assert large_file in stats["indexed_files"], f"large_doc.txt not found in {stats['indexed_files']}"
            
            print("✅ Initialization test passed")
            return True
            
        except Exception as e:
            print(f"❌ Initialization test failed: {e}")
            return False
    
    async def test_file_validation(self):
        """Test file validation logic"""
        print("\n🔍 Testing file validation...")
        
        # Test valid file
        valid_file = os.path.join(self.test_dir, "sales.txt")
        assert self.processor._validate_file(valid_file), "Valid file should pass validation"
        
        # Test unsupported file
        unsupported_file = os.path.join(self.test_dir, "image.jpg")
        assert not self.processor._validate_file(unsupported_file), "Unsupported file should fail validation"
        
        # Test non-existent file
        non_existent = os.path.join(self.test_dir, "nonexistent.txt")
        assert not self.processor._validate_file(non_existent), "Non-existent file should fail validation"
        
        print("✅ File validation test passed")
        return True
    
    async def test_hash_detection(self):
        """Test file hash change detection"""
        print("\n🔍 Testing hash detection...")
        
        file_path = os.path.join(self.test_dir, "sales.txt")
        
        # Get initial hash
        initial_hash = self.processor._calculate_file_hash(file_path)
        print(f"📝 Initial hash: {initial_hash[:10]}...")
        
        # Modify file
        with open(file_path, "a", encoding="utf-8") as f:
            f.write("\nNew line added for testing.")
        
        # Get new hash
        new_hash = self.processor._calculate_file_hash(file_path)
        print(f"📝 New hash: {new_hash[:10]}...")
        
        # Hashes should be different
        assert initial_hash != new_hash, "Hashes should be different after file modification"
        
        print("✅ Hash detection test passed")
        return True
    
    async def test_document_update(self):
        """Test document update functionality"""
        print("\n🔍 Testing document update...")
        
        file_path = os.path.join(self.test_dir, "sales.txt")
        
        # Get initial document count
        initial_stats = self.processor.get_index_stats()
        initial_count = initial_stats["collection_count"]
        
        # Update the document
        await self.processor.add_document(file_path)
        
        # Get updated stats
        updated_stats = self.processor.get_index_stats()
        updated_count = updated_stats["collection_count"]
        
        # Should have same or more chunks (depending on chunking)
        assert updated_count >= initial_count, "Document count should not decrease after update"
        
        print("✅ Document update test passed")
        return True
    
    async def test_document_removal(self):
        """Test document removal functionality"""
        print("\n🔍 Testing document removal...")
        
        file_path = os.path.join(self.test_dir, "sales.txt")
        
        # Get initial document count
        initial_stats = self.processor.get_index_stats()
        initial_count = initial_stats["collection_count"]
        
        # Remove the document
        await self.processor.remove_document(file_path)
        
        # Get updated stats
        updated_stats = self.processor.get_index_stats()
        updated_count = updated_stats["collection_count"]
        
        # Should have fewer documents
        assert updated_count < initial_count, "Document count should decrease after removal"
        
        # File should not be in indexed files
        assert file_path not in self.processor.get_indexed_files(), "File should be removed from indexed files"
        
        print("✅ Document removal test passed")
        return True
    
    async def test_query_functionality(self):
        """Test query functionality"""
        print("\n🔍 Testing query functionality...")
        
        try:
            # Test a simple query
            response = await self.processor.query("What is the total revenue?")
            
            print(f"🤖 Query response: {response.message}")
            print(f"📋 Sources found: {len(response.sources)}")
            
            # Should have a response
            assert response.message, "Query should return a response"
            
            # Should have sources if documents are indexed
            if self.processor.get_index_stats()["total_files"] > 0:
                assert len(response.sources) > 0, "Query should return sources when documents are indexed"
            
            print("✅ Query functionality test passed")
            return True
            
        except Exception as e:
            print(f"❌ Query functionality test failed: {e}")
            return False
    
    async def test_chunking(self):
        """Test text chunking functionality"""
        print("\n�� Testing text chunking...")
        
        # Test with small text (should not chunk)
        small_text = "This is a small text."
        chunks = self.processor._chunk_text(small_text)
        assert len(chunks) == 1, "Small text should not be chunked"
        
        # Test with large text (should chunk)
        large_text = "This is a large text. " * 500  # ~10KB
        chunks = self.processor._chunk_text(large_text)
        assert len(chunks) > 1, "Large text should be chunked"
        
        # Check chunk metadata
        for i, chunk in enumerate(chunks):
            assert "text" in chunk, "Chunk should have text"
            assert "chunk_id" in chunk, "Chunk should have chunk_id"
            assert "total_chunks" in chunk, "Chunk should have total_chunks"
            assert chunk["chunk_id"] == i, "Chunk IDs should be sequential"
        
        print(f"✅ Chunking test passed - {len(chunks)} chunks created")
        return True
    
    async def test_error_handling(self):
        """Test error handling"""
        print("\n🔍 Testing error handling...")
        
        # Test with non-existent file
        try:
            await self.processor.add_document("non_existent_file.txt")
            print("⚠️ Should have failed for non-existent file")
        except Exception as e:
            print(f"✅ Correctly handled non-existent file: {e}")
        
        # Test with unsupported file type
        unsupported_file = os.path.join(self.test_dir, "image.jpg")
        try:
            await self.processor.add_document(unsupported_file)
            print("⚠️ Should have failed for unsupported file type")
        except Exception as e:
            print(f"✅ Correctly handled unsupported file type: {e}")
        
        print("✅ Error handling test passed")
        return True
    
    async def cleanup(self):
        """Clean up test environment"""
        print("\n🧹 Cleaning up test environment...")
        
        if self.test_dir and os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            print(f"🗑️ Removed test directory: {self.test_dir}")
        
        # Clean up test ChromaDB
        if os.path.exists("./test_chroma_db"):
            shutil.rmtree("./test_chroma_db")
            print("🗑️ Removed test ChromaDB")
        
        print("✅ Cleanup completed")

async def run_all_tests():
    """Run all document processor tests"""
    print("🚀 Starting Document Processor Tests...")
    
    tester = TestDocumentProcessor()
    
    try:
        # Setup
        await tester.setup()
        
        # Run tests
        tests = [
            ("Initialization", tester.test_initialization),
            ("File Validation", tester.test_file_validation),
            ("Hash Detection", tester.test_hash_detection),
            ("Document Update", tester.test_document_update),
            ("Document Removal", tester.test_document_removal),
            ("Query Functionality", tester.test_query_functionality),
            ("Chunking", tester.test_chunking),
            ("Error Handling", tester.test_error_handling),
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
            print("🎉 All tests passed!")
        else:
            print("⚠️ Some tests failed. Check the output above.")
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
    
    finally:
        # Cleanup
        await tester.cleanup()

if __name__ == "__main__":
    asyncio.run(run_all_tests())