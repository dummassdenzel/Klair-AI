# OCR Support Implementation Plan

## Current State Analysis

### ✅ What's Working
1. **Text-based PDF Extraction**: PyMuPDF (fitz) extracts text from PDFs with selectable text
2. **Document Processing Pipeline**: Complete RAG pipeline for text-based documents
3. **File Validation**: FileValidator checks file types and sizes
4. **Text Extraction Service**: TextExtractor handles multiple formats (PDF, DOCX, TXT, XLSX, PPTX)

### ❌ What's Missing
1. **Scanned PDF Support**: PDFs that are image-based (scanned documents) cannot be processed
2. **Image File Support**: Image files (JPG, PNG, TIFF) containing documents cannot be processed
3. **OCR Detection**: No automatic detection of scanned vs. text-based PDFs
4. **OCR Service**: No OCR capability to extract text from images

## Recommended Solution: Tesseract OCR Integration

### Why Tesseract?
1. **Free and Open Source**: No licensing costs
2. **Mature and Reliable**: Industry-standard OCR engine
3. **Multi-language Support**: Supports 100+ languages
4. **Python Integration**: Excellent `pytesseract` library
5. **Consistent with Architecture**: Similar pattern to LibreOffice integration
6. **Performance**: Fast and efficient for most use cases

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│              Document Processing Flow                    │
└─────────────────────────────────────────────────────────┘

1. File Detection
   ├─ PDF File
   │  ├─ Try text extraction (PyMuPDF)
   │  ├─ If text found → Use extracted text ✅
   │  └─ If no text → Detect as scanned → OCR ✅
   │
   └─ Image File (.jpg, .png, .tiff, .bmp)
      └─ Direct OCR processing ✅

2. OCR Processing
   ├─ Check cache (hash-based)
   ├─ If cached → Return cached text
   └─ If not cached:
      ├─ Run Tesseract OCR
      ├─ Cache result
      └─ Return extracted text

3. Integration
   └─ Text flows into existing pipeline (chunking → embedding → indexing)
```

## Implementation Plan

### Phase 1: OCR Service Module

**File**: `ai/services/document_processor/extraction/ocr_service.py`

**Responsibilities:**
- Detect if PDF is scanned (no extractable text)
- Perform OCR on scanned PDFs and image files
- Cache OCR results (similar to PPTX converter)
- Handle Tesseract installation detection
- Support multiple image formats

**Key Methods:**
```python
class OCRService:
    - __init__(tesseract_path, cache_dir, languages)
    - is_available() -> bool
    - detect_scanned_pdf(pdf_path) -> bool
    - extract_text_from_image(image_path) -> str
    - extract_text_from_scanned_pdf(pdf_path) -> str
    - extract_text_async(file_path) -> str  # Main entry point
    - _get_cache_path(file_path) -> Path
    - _is_cache_valid(file_path, cache_path) -> bool
```

### Phase 2: Integration with TextExtractor

**File**: `ai/services/document_processor/extraction/text_extractor.py`

**Changes:**
1. Add OCR service instance
2. Modify `_extract_pdf()` to:
   - First try text extraction (existing)
   - If no text found, check if OCR is available
   - If OCR available, use OCR service
   - If OCR not available, return empty string with warning
3. Add `_extract_image()` method for image files
4. Update `_extract_text_sync()` to handle image extensions

**Supported Image Formats:**
- `.jpg`, `.jpeg` - JPEG images
- `.png` - PNG images
- `.tiff`, `.tif` - TIFF images
- `.bmp` - Bitmap images

### Phase 3: File Validator Updates

**File**: `ai/services/document_processor/extraction/file_validator.py`

**Changes:**
1. Add image extensions to `supported_extensions`
2. Update validation logic to accept image files
3. Consider image file size limits (images can be large)

### Phase 4: Configuration

**File**: `ai/config.py`

**New Settings:**
```python
# OCR settings
TESSERACT_PATH: str = os.getenv("TESSERACT_PATH", "")  # Auto-detect if empty
OCR_CACHE_DIR: str = os.getenv("OCR_CACHE_DIR", "./ocr_cache")
OCR_CACHE_ENABLED: bool = os.getenv("OCR_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
OCR_LANGUAGES: str = os.getenv("OCR_LANGUAGES", "eng")  # Comma-separated: "eng,spa,fra"
OCR_TIMEOUT: int = int(os.getenv("OCR_TIMEOUT", "300"))  # 5 minutes for large images
```

### Phase 5: Orchestrator Integration

**File**: `ai/services/document_processor/orchestrator.py`

**Changes:**
1. Initialize OCR service in `__init__`
2. Pass OCR service to TextExtractor
3. No other changes needed (TextExtractor handles it internally)

### Phase 6: Dependencies

**File**: `ai/requirements.txt`

**New Dependencies:**
```
pytesseract==0.3.13  # Python wrapper for Tesseract OCR
Pillow==11.0.0       # Image processing (required by pytesseract)
```

**System Dependency:**
- Tesseract OCR must be installed on the system
- Installation instructions will be provided

## Technical Details

### Scanned PDF Detection

**Strategy:**
1. Extract text using PyMuPDF (existing method)
2. If extracted text length < threshold (e.g., 50 characters per page), consider it scanned
3. Alternative: Check if PDF contains images (PyMuPDF can detect this)
4. Use OCR if detected as scanned

**Implementation:**
```python
def detect_scanned_pdf(pdf_path: str) -> bool:
    """Detect if PDF is scanned (image-based)"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        total_text_length = 0
        total_pages = len(doc)
        
        for page in doc:
            text = page.get_text()
            total_text_length += len(text.strip())
        
        doc.close()
        
        # If average text per page < threshold, likely scanned
        avg_text_per_page = total_text_length / total_pages if total_pages > 0 else 0
        return avg_text_per_page < 50  # Threshold: 50 chars per page
    except Exception:
        return True  # If extraction fails, assume scanned
```

### OCR Caching Strategy

**Similar to PPTX Converter:**
- Cache key: SHA256 hash of file content
- Cache format: Plain text file (`.txt`)
- Cache validation: Compare file modification time
- Cache location: `./ocr_cache/` directory

**Benefits:**
- Avoid re-OCR of unchanged files
- Faster processing for repeated access
- Reduced CPU usage

### Error Handling

**Graceful Degradation:**
- If Tesseract not installed: Log warning, skip OCR, return empty text
- If OCR fails: Log error, return empty text, mark document as error
- If image corrupted: Log error, skip processing

**User Feedback:**
- Document status in database: `"indexed"`, `"error"`, or `"ocr_failed"`
- Log messages indicate OCR availability and results

## File Structure

```
ai/services/document_processor/extraction/
├── __init__.py                    # Export OCRService
├── text_extractor.py             # Updated with OCR integration
├── file_validator.py             # Updated with image support
├── ocr_service.py                # NEW: OCR service
└── ...

ai/config.py                      # Updated with OCR settings
ai/requirements.txt               # Updated with OCR dependencies
```

## Testing Strategy

### Unit Tests
1. Test OCR service initialization
2. Test scanned PDF detection
3. Test OCR text extraction from images
4. Test cache hit/miss scenarios
5. Test error handling (missing Tesseract, corrupted files)

### Integration Tests
1. Test full flow: Image file → OCR → Text → Chunking → Indexing
2. Test scanned PDF → OCR → Text → Chunking → Indexing
3. Test cache invalidation on file update
4. Test graceful degradation when Tesseract not installed

### Manual Testing
1. Test with scanned PDF files
2. Test with various image formats (JPG, PNG, TIFF)
3. Test with multi-page TIFF files
4. Test with large images (>10MB)
5. Test with poor quality scans
6. Test with multi-language documents

## Performance Considerations

### Optimization Strategies
1. **Caching**: Avoid re-OCR of unchanged files
2. **Async Processing**: OCR runs in thread pool (CPU-intensive)
3. **Image Preprocessing**: Optional image enhancement (deskew, denoise)
4. **Page Limits**: For very large PDFs, limit pages processed
5. **Timeout**: Set reasonable timeout for OCR operations

### Expected Performance
- **Small Image (<1MB)**: 2-5 seconds OCR
- **Medium Image (1-5MB)**: 5-15 seconds OCR
- **Large Image (>5MB)**: 15-60 seconds OCR
- **Scanned PDF (10 pages)**: 30-120 seconds OCR
- **Cache Hit**: < 100ms (file read)

### Resource Usage
- **CPU**: High during OCR (single-threaded Tesseract)
- **Memory**: Moderate (image loading into memory)
- **Disk**: Cache storage (text files are small)

## Security Considerations

1. **Path Validation**: Ensure file paths are within allowed directories
2. **File Size Limits**: Enforce maximum file size for OCR (prevent DoS)
3. **Cache Directory**: Restrict access to cache directory
4. **Temporary Files**: Secure cleanup of temporary files (if any)
5. **Image Validation**: Validate image files before processing

## Installation Requirements

### System Dependencies

**Windows:**
```bash
# Download and install Tesseract from:
# https://github.com/UB-Mannheim/tesseract/wiki
# Add to PATH or set TESSERACT_PATH environment variable
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install tesseract-ocr
sudo apt-get install tesseract-ocr-eng  # English language pack
# For other languages: tesseract-ocr-spa, tesseract-ocr-fra, etc.
```

**macOS:**
```bash
brew install tesseract
brew install tesseract-lang  # Language packs
```

### Python Dependencies
```bash
pip install pytesseract Pillow
```

## Future Enhancements

1. **Image Preprocessing**: Auto-deskew, denoise, contrast enhancement
2. **Multi-language Detection**: Auto-detect document language
3. **Layout Analysis**: Preserve document structure (tables, columns)
4. **Confidence Scores**: Store OCR confidence per chunk
5. **Batch Processing**: Process multiple images in parallel
6. **Alternative OCR Engines**: Support for EasyOCR, PaddleOCR (optional)
7. **PDF Generation**: Convert OCR'd images back to searchable PDFs

## Migration Path

1. **Phase 1**: Implement OCR service (standalone)
2. **Phase 2**: Integrate with TextExtractor
3. **Phase 3**: Update FileValidator and config
4. **Phase 4**: Test with sample documents
5. **Phase 5**: Deploy and monitor performance

## Consistency with Existing Code

### Following Existing Patterns:
1. **Service Pattern**: Similar to `PPTXConverter` - separate service class
2. **Caching Pattern**: Same hash-based caching as PPTX converter
3. **Async Pattern**: Uses `run_in_executor` like other extractors
4. **Error Handling**: Graceful degradation like other services
5. **Configuration**: Environment variables in `config.py`
6. **Logging**: Consistent logging patterns

### Avoiding Duplication:
1. **Reuse TextExtractor**: Extend existing class, don't duplicate
2. **Reuse FileValidator**: Extend existing validation, don't duplicate
3. **Reuse Cache Pattern**: Similar structure to PPTX cache
4. **Reuse Orchestrator**: No major changes needed

## Questions to Consider

1. **Image File Size Limits**: Should we limit image file sizes? (Recommend: 50MB default)
2. **OCR Quality**: Should we implement image preprocessing? (Recommend: Start simple, add later)
3. **Multi-page Images**: How to handle TIFF files with multiple pages? (Recommend: Process all pages)
4. **Language Support**: Default to English only or multi-language? (Recommend: Configurable, default English)
5. **Performance**: Should OCR be async/background for large files? (Recommend: Already async via thread pool)

## Success Criteria

✅ Scanned PDFs are automatically detected and processed with OCR
✅ Image files (JPG, PNG, TIFF) are supported and processed
✅ OCR results are cached to avoid re-processing
✅ System gracefully handles missing Tesseract installation
✅ OCR integrates seamlessly with existing document processing pipeline
✅ Performance is acceptable for typical document sizes
✅ Code follows existing patterns and maintains consistency

