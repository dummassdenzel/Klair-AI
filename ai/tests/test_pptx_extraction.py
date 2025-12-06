"""
Test script to extract text from the provided PPTX files.
This will help diagnose why one file is not being indexed properly.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.document_processor.extraction import TextExtractor
import logging

# Set up logging to see detailed output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_pptx_file(file_path: str):
    """Test extraction from a single PPTX file"""
    print("\n" + "="*80)
    print(f"TESTING: {Path(file_path).name}")
    print("="*80)
    
    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return
    
    print(f"📄 File path: {file_path}")
    print(f"📊 File size: {Path(file_path).stat().st_size / 1024:.2f} KB")
    
    extractor = TextExtractor()
    
    try:
        print("\n🔄 Starting extraction...")
        result = await extractor.extract_text_async(file_path)
        
        print(f"\n✅ Extraction completed!")
        print(f"📝 Extracted text length: {len(result)} characters")
        print(f"📄 Number of lines: {len(result.splitlines())}")
        
        if result:
            print(f"\n📋 First 500 characters of extracted content:")
            print("-" * 80)
            print(result[:500])
            print("-" * 80)
            
            if len(result) > 500:
                print(f"\n📋 Last 500 characters of extracted content:")
                print("-" * 80)
                print(result[-500:])
                print("-" * 80)
            
            # Count slides mentioned
            slide_count = result.count("Slide ")
            print(f"\n📊 Slides detected in output: {slide_count}")
            
            # Show slide breakdown
            lines = result.splitlines()
            slide_lines = [line for line in lines if line.startswith("Slide ")]
            print(f"📊 Slide headers found: {len(slide_lines)}")
            if slide_lines:
                print("   Slide headers:")
                for slide_line in slide_lines[:10]:  # Show first 10
                    print(f"   - {slide_line}")
                if len(slide_lines) > 10:
                    print(f"   ... and {len(slide_lines) - 10} more")
        else:
            print("❌ No content extracted!")
            
    except Exception as e:
        print(f"\n❌ Extraction failed with error:")
        print(f"   Error type: {type(e).__name__}")
        print(f"   Error message: {str(e)}")
        import traceback
        print(f"\n📋 Full traceback:")
        traceback.print_exc()

async def main():
    """Test both PPTX files"""
    # Get the documents folder path
    documents_folder = Path(__file__).parent.parent.parent / "documents"
    
    print("="*80)
    print("PPTX EXTRACTION DIAGNOSTIC TEST")
    print("="*80)
    print(f"📁 Documents folder: {documents_folder}")
    
    # Find all PPTX files
    pptx_files = list(documents_folder.glob("*.pptx"))
    
    if not pptx_files:
        print(f"\n❌ No PPTX files found in {documents_folder}")
        return
    
    print(f"\n📄 Found {len(pptx_files)} PPTX file(s):")
    for pptx_file in pptx_files:
        print(f"   - {pptx_file.name} ({pptx_file.stat().st_size / 1024:.2f} KB)")
    
    # Test each file
    for pptx_file in pptx_files:
        await test_pptx_file(str(pptx_file))
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())

