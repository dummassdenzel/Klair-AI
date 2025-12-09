"""
Quick OCR Test

Simple test to verify OCR functionality is working.
Run this to quickly check if OCR is set up correctly.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor.extraction.ocr_service import OCRService


async def quick_test():
    """Quick test of OCR functionality"""
    print("🚀 Quick OCR Test")
    print("=" * 60)
    
    # Initialize OCR service
    print("\n1️⃣ Initializing OCR Service...")
    try:
        from config import settings
        ocr_service = OCRService(
            tesseract_path=settings.TESSERACT_PATH if settings.TESSERACT_PATH else None,
            cache_dir="./ocr_cache",
            languages=settings.OCR_LANGUAGES
        )
    except ImportError:
        ocr_service = OCRService(cache_dir="./ocr_cache")
    
    # Check availability
    is_available = ocr_service.is_available()
    print(f"   Tesseract available: {is_available}")
    
    if not is_available:
        print("\n❌ Tesseract OCR is not installed or not found!")
        print("\n📋 Installation Instructions:")
        print("   Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki")
        print("   Linux:   sudo apt-get install tesseract-ocr tesseract-ocr-eng")
        print("   macOS:   brew install tesseract tesseract-lang")
        return False
    
    print(f"   ✅ Tesseract found at: {ocr_service.tesseract_path}")
    print(f"   Languages: {ocr_service.languages}")
    
    # Check for test documents
    print("\n2️⃣ Checking for test documents...")
    project_root = Path(__file__).parent.parent.parent
    documents_dir = project_root / "documents"
    
    if not documents_dir.exists():
        print(f"   ⚠️ Documents directory not found: {documents_dir}")
        print("   💡 Place scanned PDFs or images in the /documents folder to test")
        return True
    
    pdf_files = list(documents_dir.glob("*.pdf"))
    image_files = list(documents_dir.glob("*.{jpg,jpeg,png,tiff,tif,bmp}"))
    
    print(f"   Found {len(pdf_files)} PDF files")
    print(f"   Found {len(image_files)} image files")
    
    if not pdf_files and not image_files:
        print("   ⚠️ No test files found in documents directory")
        print("   💡 Place scanned PDFs or images in the /documents folder to test")
        return True
    
    # Test scanned PDF detection
    if pdf_files:
        print("\n3️⃣ Testing scanned PDF detection...")
        test_pdf = pdf_files[0]
        print(f"   Testing: {test_pdf.name}")
        
        try:
            is_scanned = ocr_service.detect_scanned_pdf(str(test_pdf))
            print(f"   Detected as scanned: {is_scanned}")
            
            if is_scanned:
                print("\n4️⃣ Testing OCR extraction from scanned PDF...")
                print("   ⏳ This may take a while...")
                text = await ocr_service.extract_text_from_scanned_pdf(str(test_pdf))
                
                if text:
                    print(f"   ✅ Extracted {len(text)} characters")
                    print(f"   Preview: {text[:150]}...")
                else:
                    print("   ⚠️ No text extracted (may be blank or poor quality)")
            else:
                print("   ℹ️ PDF has extractable text, OCR not needed")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # Test image OCR
    if image_files:
        print("\n5️⃣ Testing OCR extraction from image...")
        test_image = image_files[0]
        print(f"   Testing: {test_image.name}")
        
        try:
            print("   ⏳ This may take a while...")
            text = await ocr_service.extract_text_from_image(str(test_image))
            
            if text:
                print(f"   ✅ Extracted {len(text)} characters")
                print(f"   Preview: {text[:150]}...")
            else:
                print("   ⚠️ No text extracted (may be blank or poor quality)")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    print("\n" + "=" * 60)
    print("✅ Quick OCR test completed successfully!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(quick_test())
    sys.exit(0 if success else 1)

