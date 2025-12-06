"""
Test script to simulate the full indexing process for PPTX files.
This will help diagnose why files are not being indexed properly.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.document_processor.extraction import FileValidator, TextExtractor, DocumentChunker
import logging

# Set up logging to see detailed output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_full_indexing_process(file_path: str):
    """Test the full indexing process for a single PPTX file"""
    print("\n" + "="*80)
    print(f"FULL INDEXING TEST: {Path(file_path).name}")
    print("="*80)
    
    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return
    
    print(f"📄 File path: {file_path}")
    print(f"📊 File size: {Path(file_path).stat().st_size / 1024:.2f} KB")
    
    # Step 1: File Validation
    print("\n" + "-"*80)
    print("STEP 1: File Validation")
    print("-"*80)
    validator = FileValidator()
    is_valid, error = validator.validate_file(file_path)
    print(f"✅ Valid: {is_valid}")
    if not is_valid:
        print(f"❌ Error: {error}")
        return
    else:
        print(f"✅ File is valid and supported")
    
    # Step 2: Check if supported
    print("\n" + "-"*80)
    print("STEP 2: Check Support")
    print("-"*80)
    is_supported = validator.is_supported_file(file_path)
    print(f"✅ Supported: {is_supported}")
    if not is_supported:
        print(f"❌ File extension not in supported list: {validator.supported_extensions}")
        return
    
    # Step 3: Extract Metadata
    print("\n" + "-"*80)
    print("STEP 3: Extract Metadata")
    print("-"*80)
    try:
        metadata = validator.extract_file_metadata(file_path)
        print(f"✅ Metadata extracted:")
        print(f"   - File type: {metadata.get('file_type')}")
        print(f"   - Size: {metadata.get('size_mb')} MB")
        print(f"   - Hash: {metadata.get('hash')[:16]}...")
    except Exception as e:
        print(f"❌ Metadata extraction failed: {e}")
        return
    
    # Step 4: Text Extraction
    print("\n" + "-"*80)
    print("STEP 4: Text Extraction")
    print("-"*80)
    extractor = TextExtractor()
    try:
        text = await extractor.extract_text_async(file_path)
        print(f"✅ Text extracted: {len(text)} characters")
        if not text or not text.strip():
            print(f"❌ WARNING: Text is empty or whitespace only!")
            print(f"   This would cause the file to be marked as 'error' status")
            return
        else:
            print(f"✅ Text has content")
            print(f"   First 200 chars: {text[:200]}...")
    except Exception as e:
        print(f"❌ Text extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 5: Chunking
    print("\n" + "-"*80)
    print("STEP 5: Chunking")
    print("-"*80)
    try:
        chunker = DocumentChunker(chunk_size=1000, chunk_overlap=200)
        chunks = chunker.create_chunks(text, file_path)
        print(f"✅ Created {len(chunks)} chunks")
        if len(chunks) == 0:
            print(f"❌ WARNING: No chunks created!")
            return
        else:
            print(f"   First chunk preview: {chunks[0].text[:100]}...")
    except Exception as e:
        print(f"❌ Chunking failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Summary
    print("\n" + "="*80)
    print("INDEXING TEST SUMMARY")
    print("="*80)
    print(f"✅ File: {Path(file_path).name}")
    print(f"✅ Validation: PASSED")
    print(f"✅ Support Check: PASSED")
    print(f"✅ Metadata: EXTRACTED")
    print(f"✅ Text Extraction: {len(text)} characters")
    print(f"✅ Chunking: {len(chunks)} chunks")
    print(f"\n✅ ALL STEPS PASSED - File should be indexable!")

async def main():
    """Test both PPTX files with full indexing process"""
    # Get the documents folder path
    documents_folder = Path(__file__).parent.parent.parent / "documents"
    
    print("="*80)
    print("PPTX FULL INDEXING PROCESS TEST")
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
        await test_full_indexing_process(str(pptx_file))
    
    print("\n" + "="*80)
    print("ALL TESTS COMPLETE")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())

