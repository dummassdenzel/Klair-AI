"""
OCR Functionality Tests

Tests for OCR service, scanned PDF detection, and image processing.
"""

import asyncio
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor.extraction.ocr_service import OCRService
from services.document_processor.extraction.text_extractor import TextExtractor
from services.document_processor.extraction.file_validator import FileValidator
from services.document_processor import DocumentProcessorOrchestrator


class TestOCR:
    """Test suite for OCR functionality"""
    
    def __init__(self):
        self.test_dir = None
        self.documents_dir = None
        self.ocr_service = None
        self.processor = None
    
    async def setup(self):
        """Set up test environment"""
        print("🧪 Setting up OCR test environment...")
        
        # Get documents directory
        project_root = Path(__file__).parent.parent.parent
        self.documents_dir = project_root / "documents"
        
        # Create temporary directory for test files
        self.test_dir = tempfile.mkdtemp(prefix="test_ocr_")
        print(f"📁 Test directory: {self.test_dir}")
        print(f"📁 Documents directory: {self.documents_dir}")
        
        # Initialize OCR service
        try:
            from config import settings
            self.ocr_service = OCRService(
                tesseract_path=settings.TESSERACT_PATH if settings.TESSERACT_PATH else None,
                cache_dir=str(Path(self.test_dir) / "ocr_cache"),
                languages=settings.OCR_LANGUAGES
            )
        except ImportError:
            # Use defaults if settings not available
            self.ocr_service = OCRService(
                cache_dir=str(Path(self.test_dir) / "ocr_cache")
            )
        
        print(f"✅ OCR Service initialized: {self.ocr_service.is_available()}")
        
        # Initialize processor for integration tests
        try:
            self.processor = DocumentProcessorOrchestrator(
                persist_dir=str(Path(self.test_dir) / "test_chroma_db")
            )
            print("✅ Document processor initialized")
        except Exception as e:
            print(f"⚠️ Could not initialize processor: {e}")
            self.processor = None
    
    def test_ocr_service_initialization(self):
        """Test OCR service initialization"""
        print("\n🔍 Testing OCR service initialization...")
        
        assert self.ocr_service is not None, "OCR service should be initialized"
        assert hasattr(self.ocr_service, 'is_available'), "OCR service should have is_available method"
        
        is_available = self.ocr_service.is_available()
        print(f"📊 Tesseract available: {is_available}")
        
        if is_available:
            print(f"✅ OCR Service is available at: {self.ocr_service.tesseract_path}")
        else:
            print("⚠️ Tesseract not found - some tests will be skipped")
        
        print("✅ OCR service initialization test passed")
        return True
    
    def test_scanned_pdf_detection(self):
        """Test scanned PDF detection"""
        print("\n🔍 Testing scanned PDF detection...")
        
        if not self.ocr_service.is_available():
            print("⚠️ Skipping - Tesseract not available")
            return True
        
        # Check if documents directory has PDF files
        if not self.documents_dir.exists():
            print("⚠️ Documents directory not found, skipping test")
            return True
        
        pdf_files = list(self.documents_dir.glob("*.pdf"))
        if not pdf_files:
            print("⚠️ No PDF files found in documents directory, skipping test")
            return True
        
        # Test detection on first PDF
        test_pdf = pdf_files[0]
        print(f"📄 Testing PDF: {test_pdf.name}")
        
        try:
            is_scanned = self.ocr_service.detect_scanned_pdf(str(test_pdf))
            print(f"📊 Detected as scanned: {is_scanned}")
            
            # Test should complete without error
            assert isinstance(is_scanned, bool), "detect_scanned_pdf should return boolean"
            
            print("✅ Scanned PDF detection test passed")
            return True
            
        except Exception as e:
            print(f"❌ Scanned PDF detection failed: {e}")
            return False
    
    async def test_ocr_from_scanned_pdf(self):
        """Test OCR extraction from scanned PDF"""
        print("\n🔍 Testing OCR extraction from scanned PDF...")
        
        if not self.ocr_service.is_available():
            print("⚠️ Skipping - Tesseract not available")
            return True
        
        # Check if documents directory has PDF files
        if not self.documents_dir.exists():
            print("⚠️ Documents directory not found, skipping test")
            return True
        
        pdf_files = list(self.documents_dir.glob("*.pdf"))
        if not pdf_files:
            print("⚠️ No PDF files found in documents directory, skipping test")
            return True
        
        # Test OCR on first PDF
        test_pdf = pdf_files[0]
        print(f"📄 Testing OCR on: {test_pdf.name}")
        
        try:
            # First check if it's scanned
            is_scanned = self.ocr_service.detect_scanned_pdf(str(test_pdf))
            
            if not is_scanned:
                print("⚠️ PDF has extractable text, skipping OCR test")
                return True
            
            print("🔄 Running OCR (this may take a while)...")
            text = await self.ocr_service.extract_text_from_scanned_pdf(str(test_pdf))
            
            print(f"📊 Extracted {len(text)} characters")
            print(f"📝 Preview: {text[:200]}..." if text else "⚠️ No text extracted")
            
            # Should complete without error (even if no text extracted)
            assert isinstance(text, str), "OCR should return string"
            
            if text:
                print("✅ OCR extraction successful")
            else:
                print("⚠️ No text extracted (may be blank page or OCR issue)")
            
            print("✅ OCR from scanned PDF test passed")
            return True
            
        except Exception as e:
            print(f"❌ OCR extraction failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_ocr_caching(self):
        """Test OCR result caching"""
        print("\n🔍 Testing OCR caching...")
        
        if not self.ocr_service.is_available():
            print("⚠️ Skipping - Tesseract not available")
            return True
        
        # Check if documents directory has PDF files
        if not self.documents_dir.exists():
            print("⚠️ Documents directory not found, skipping test")
            return True
        
        pdf_files = list(self.documents_dir.glob("*.pdf"))
        if not pdf_files:
            print("⚠️ No PDF files found in documents directory, skipping test")
            return True
        
        test_pdf = pdf_files[0]
        print(f"📄 Testing cache with: {test_pdf.name}")
        
        try:
            # First run - should create cache
            print("🔄 First OCR run (creating cache)...")
            import time
            start_time = time.time()
            text1 = await self.ocr_service.extract_text_from_scanned_pdf(str(test_pdf))
            first_run_time = time.time() - start_time
            print(f"⏱️ First run took: {first_run_time:.2f}s")
            
            # Second run - should use cache
            print("🔄 Second OCR run (should use cache)...")
            start_time = time.time()
            text2 = await self.ocr_service.extract_text_from_scanned_pdf(str(test_pdf))
            second_run_time = time.time() - start_time
            print(f"⏱️ Second run took: {second_run_time:.2f}s")
            
            # Results should be the same
            assert text1 == text2, "Cached result should match original"
            
            # Second run should be faster (cache hit)
            if first_run_time > 1.0:  # Only check if first run took significant time
                assert second_run_time < first_run_time, "Cached run should be faster"
                print(f"✅ Cache working: {second_run_time:.2f}s vs {first_run_time:.2f}s")
            
            print("✅ OCR caching test passed")
            return True
            
        except Exception as e:
            print(f"❌ OCR caching test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def test_text_extractor_integration(self):
        """Test TextExtractor integration with OCR"""
        print("\n🔍 Testing TextExtractor OCR integration...")
        
        if not self.ocr_service.is_available():
            print("⚠️ Skipping - Tesseract not available")
            return True
        
        # Create TextExtractor with OCR service
        text_extractor = TextExtractor(ocr_service=self.ocr_service)
        
        # Check if image extensions are added
        assert ".jpg" in text_extractor.supported_extensions or not self.ocr_service.is_available(), \
            "Image extensions should be added when OCR is available"
        
        print("✅ TextExtractor integration test passed")
        return True
    
    def test_file_validator_integration(self):
        """Test FileValidator integration with OCR"""
        print("\n🔍 Testing FileValidator OCR integration...")
        
        if not self.ocr_service.is_available():
            print("⚠️ Skipping - Tesseract not available")
            return True
        
        # Create FileValidator with OCR service
        file_validator = FileValidator(max_file_size_mb=50, ocr_service=self.ocr_service)
        
        # Check if image extensions are added
        assert ".jpg" in file_validator.supported_extensions or not self.ocr_service.is_available(), \
            "Image extensions should be added when OCR is available"
        
        print("✅ FileValidator integration test passed")
        return True
    
    async def test_full_pipeline_scanned_pdf(self):
        """Test full pipeline with scanned PDF"""
        print("\n🔍 Testing full pipeline with scanned PDF...")
        
        if not self.ocr_service.is_available():
            print("⚠️ Skipping - Tesseract not available")
            return True
        
        if not self.processor:
            print("⚠️ Skipping - Processor not initialized")
            return True
        
        # Check if documents directory has PDF files
        if not self.documents_dir.exists():
            print("⚠️ Documents directory not found, skipping test")
            return True
        
        pdf_files = list(self.documents_dir.glob("*.pdf"))
        if not pdf_files:
            print("⚠️ No PDF files found in documents directory, skipping test")
            return True
        
        test_pdf = pdf_files[0]
        print(f"📄 Testing full pipeline with: {test_pdf.name}")
        
        try:
            # Check if it's scanned
            is_scanned = self.ocr_service.detect_scanned_pdf(str(test_pdf))
            
            if not is_scanned:
                print("⚠️ PDF has extractable text, skipping OCR pipeline test")
                return True
            
            # Process the document
            print("🔄 Processing document through full pipeline...")
            await self.processor.add_document(str(test_pdf), use_queue=False)
            
            # Check stats
            stats = self.processor.get_stats()
            print(f"📊 Index stats: {stats['total_files']} files, {stats['total_chunks']} chunks")
            
            # Should have processed the file
            assert str(test_pdf) in stats["indexed_files"], "File should be indexed"
            
            # Try a query
            print("🔄 Testing query on OCR'd content...")
            response = await self.processor.query("What is in this document?")
            
            print(f"📝 Query response: {response.message[:200]}...")
            print(f"📋 Sources: {len(response.sources)}")
            
            # Should have a response
            assert response.message, "Query should return a response"
            
            print("✅ Full pipeline test passed")
            return True
            
        except Exception as e:
            print(f"❌ Full pipeline test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_error_handling(self):
        """Test error handling for OCR"""
        print("\n🔍 Testing OCR error handling...")
        
        # Test with non-existent file
        try:
            if self.ocr_service.is_available():
                await self.ocr_service.extract_text_from_scanned_pdf("non_existent.pdf")
                print("⚠️ Should have raised error for non-existent file")
                return False
        except (FileNotFoundError, RuntimeError) as e:
            print(f"✅ Correctly handled non-existent file: {type(e).__name__}")
        
        # Test with invalid image
        try:
            if self.ocr_service.is_available():
                # Create a fake image file
                fake_image = Path(self.test_dir) / "fake.jpg"
                fake_image.write_bytes(b"not an image")
                
                await self.ocr_service.extract_text_from_image(str(fake_image))
                print("⚠️ Should have raised error for invalid image")
                return False
        except (RuntimeError, Exception) as e:
            print(f"✅ Correctly handled invalid image: {type(e).__name__}")
        
        print("✅ Error handling test passed")
        return True
    
    async def cleanup(self):
        """Clean up test environment"""
        print("\n🧹 Cleaning up OCR test environment...")
        
        if self.processor:
            try:
                await self.processor.cleanup()
                print("🧹 Cleaned up document processor")
            except Exception as e:
                print(f"⚠️ Error cleaning processor: {e}")
        
        if self.test_dir and os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
                print(f"🗑️ Removed test directory: {self.test_dir}")
            except Exception as e:
                print(f"⚠️ Error removing test directory: {e}")
        
        print("✅ Cleanup completed")


async def run_all_tests():
    """Run all OCR tests"""
    print("🚀 Starting OCR Functionality Tests...")
    print("=" * 60)
    
    tester = TestOCR()
    
    try:
        # Setup
        await tester.setup()
        
        # Run tests
        tests = [
            ("OCR Service Initialization", tester.test_ocr_service_initialization, False),
            ("Scanned PDF Detection", tester.test_scanned_pdf_detection, False),
            ("OCR from Scanned PDF", tester.test_ocr_from_scanned_pdf, True),
            ("OCR Caching", tester.test_ocr_caching, True),
            ("TextExtractor Integration", tester.test_text_extractor_integration, False),
            ("FileValidator Integration", tester.test_file_validator_integration, False),
            ("Full Pipeline Test", tester.test_full_pipeline_scanned_pdf, True),
            ("Error Handling", tester.test_error_handling, True),
        ]
        
        passed = 0
        total = len(tests)
        skipped = 0
        
        for test_name, test_func, is_async in tests:
            print(f"\n{'='*60}")
            print(f"🧪 Running: {test_name}")
            print(f"{'='*60}")
            
            try:
                if is_async:
                    result = await test_func()
                else:
                    result = test_func()
                
                if result:
                    passed += 1
                    print(f"✅ {test_name}: PASSED")
                else:
                    print(f"❌ {test_name}: FAILED")
            except Exception as e:
                error_msg = str(e).lower()
                if "skipping" in error_msg or "not available" in error_msg or "not found" in error_msg:
                    skipped += 1
                    print(f"⏭️ {test_name}: SKIPPED - {e}")
                else:
                    print(f"❌ {test_name}: ERROR - {e}")
                    import traceback
                    traceback.print_exc()
        
        # Summary
        print(f"\n{'='*60}")
        print(f"📊 TEST SUMMARY")
        print(f"{'='*60}")
        print(f"✅ Passed: {passed}/{total}")
        print(f"❌ Failed: {total - passed - skipped}/{total}")
        print(f"⏭️ Skipped: {skipped}/{total}")
        if total > 0:
            print(f"📈 Success Rate: {(passed/(total-skipped))*100:.1f}%" if (total-skipped) > 0 else "N/A")
        
        if passed == (total - skipped):
            print("🎉 All applicable tests passed!")
        else:
            print("⚠️ Some tests failed. Check the output above.")
        
        # OCR availability notice
        if not tester.ocr_service or not tester.ocr_service.is_available():
            print("\n" + "=" * 60)
            print("⚠️ IMPORTANT: Tesseract OCR is not installed or not found.")
            print("   Some tests were skipped. To enable OCR functionality:")
            print("   - Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki")
            print("   - Linux: sudo apt-get install tesseract-ocr tesseract-ocr-eng")
            print("   - macOS: brew install tesseract tesseract-lang")
            print("=" * 60)
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        await tester.cleanup()


if __name__ == "__main__":
    asyncio.run(run_all_tests())

