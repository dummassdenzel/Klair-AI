# OCR Tests

This directory contains tests for OCR (Optical Character Recognition) functionality.

## Test Files

### `test_ocr.py`
Comprehensive test suite for OCR functionality including:
- OCR service initialization
- Scanned PDF detection
- OCR extraction from scanned PDFs
- OCR extraction from images
- Caching functionality
- Integration with TextExtractor and FileValidator
- Full pipeline testing
- Error handling

### `quick_test_ocr.py`
Quick verification test to check if OCR is set up correctly. Use this for a fast check.

## Prerequisites

1. **Tesseract OCR must be installed:**
   - **Windows**: Download from https://github.com/UB-Mannheim/tesseract/wiki
   - **Linux**: `sudo apt-get install tesseract-ocr tesseract-ocr-eng`
   - **macOS**: `brew install tesseract tesseract-lang`

2. **Python dependencies:**
   ```bash
   pip install pytesseract Pillow
   ```

3. **Test documents:**
   - Place scanned PDFs or images in the `/documents` folder
   - The tests will automatically detect and use these files

## Running Tests

### Quick Test (Recommended First)
```bash
cd ai
python tests/quick_test_ocr.py
```

This will:
- Check if Tesseract is installed
- Test scanned PDF detection
- Test OCR extraction (if test files are available)

### Full Test Suite
```bash
cd ai
python tests/test_ocr.py
```

This runs all OCR tests including:
- Service initialization
- PDF detection
- OCR extraction
- Caching
- Integration tests
- Full pipeline tests

## Test Documents Location

Tests look for documents in:
- `/documents` folder (project root)

Supported formats:
- **PDFs**: Scanned PDFs (image-based, no extractable text)
- **Images**: JPG, PNG, TIFF, BMP files

## Expected Output

### Successful Test
```
🚀 Quick OCR Test
============================================================

1️⃣ Initializing OCR Service...
   Tesseract available: True
   ✅ Tesseract found at: C:\Program Files\Tesseract-OCR\tesseract.exe
   Languages: eng

2️⃣ Checking for test documents...
   Found 1 PDF files
   Found 0 image files

3️⃣ Testing scanned PDF detection...
   Testing: Receipt_2024-10-23_223404.pdf
   Detected as scanned: True

4️⃣ Testing OCR extraction from scanned PDF...
   ⏳ This may take a while...
   ✅ Extracted 245 characters
   Preview: RECEIPT Date: 2024-10-23...

============================================================
✅ Quick OCR test completed successfully!
```

### Tesseract Not Found
```
❌ Tesseract OCR is not installed or not found!

📋 Installation Instructions:
   Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki
   Linux:   sudo apt-get install tesseract-ocr tesseract-ocr-eng
   macOS:   brew install tesseract tesseract-lang
```

## Troubleshooting

### "Tesseract not found"
1. Install Tesseract OCR (see Prerequisites)
2. Add Tesseract to your system PATH, OR
3. Set `TESSERACT_PATH` in `.env`:
   ```
   TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

### "No text extracted"
- The document may be blank or very poor quality
- Try with a higher quality scanned document
- Check if the document actually contains text

### "Import errors"
- Make sure you're running from the `ai` directory
- Install dependencies: `pip install pytesseract Pillow`

### "Documents directory not found"
- Create a `/documents` folder in the project root
- Place test PDFs or images there

## Test Coverage

The test suite covers:
- ✅ OCR service initialization and availability check
- ✅ Scanned PDF detection (distinguishes scanned vs text-based PDFs)
- ✅ OCR extraction from scanned PDFs
- ✅ OCR extraction from images
- ✅ Caching (verifies cache is used on second run)
- ✅ Integration with TextExtractor
- ✅ Integration with FileValidator
- ✅ Full document processing pipeline
- ✅ Error handling (invalid files, missing files)

## Notes

- OCR processing can be slow (especially for large PDFs)
- First run creates cache, subsequent runs are faster
- Tests will skip if Tesseract is not installed (graceful degradation)
- Tests will skip if no test documents are found

