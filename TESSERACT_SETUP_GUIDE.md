# Tesseract OCR Setup Guide

## Current Status
❌ Tesseract OCR is **not installed** on your system.

## Installation Steps

### Step 1: Download Tesseract
1. Go to: https://github.com/UB-Mannheim/tesseract/wiki
2. Download the latest Windows installer (`.exe` file)
3. Recommended: Download version 5.x or later

### Step 2: Install Tesseract
1. Run the downloaded installer
2. **Important**: During installation, check the option **"Add to PATH"**
   - This allows the system to find Tesseract automatically
3. Complete the installation

### Step 3: Verify Installation
After installation, run:
```bash
python ai\tests\find_tesseract.py
```

Or test directly:
```bash
tesseract --version
```

### Step 4: Configure (if needed)
If Tesseract is installed but not found automatically:

1. Find the installation path (usually):
   - `C:\Program Files\Tesseract-OCR\tesseract.exe`
   - Or `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

2. Add to `.env` file in project root:
   ```
   TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

3. Restart your terminal/IDE

### Step 5: Test OCR
After installation, run the quick test:
```bash
cd ai
python tests\quick_test_ocr.py
```

## Quick Installation Commands

### Option 1: Manual Download (Recommended)
1. Download from: https://github.com/UB-Mannheim/tesseract/wiki
2. Install with "Add to PATH" checked
3. Restart terminal

### Option 2: Using Chocolatey (if you have it)
```bash
choco install tesseract
```

### Option 3: Using Scoop (if you have it)
```bash
scoop install tesseract
```

## After Installation

1. **Restart your terminal/IDE** (important!)
2. Run the finder script to verify:
   ```bash
   python ai\tests\find_tesseract.py
   ```
3. Run the quick OCR test:
   ```bash
   cd ai
   python tests\quick_test_ocr.py
   ```

## Troubleshooting

### "Tesseract not found" after installation
1. **Restart your terminal/IDE** - PATH changes require restart
2. Check if it's in PATH:
   ```bash
   where tesseract.exe
   ```
3. If not in PATH, set `TESSERACT_PATH` in `.env` file

### "Permission denied" errors
- Run terminal as Administrator
- Or install to a user directory instead of Program Files

### Installation fails
- Make sure you have administrator rights
- Try installing to a different location
- Check Windows Defender/antivirus isn't blocking

## Language Packs

By default, Tesseract includes English. For other languages:

1. Download language packs from: https://github.com/tesseract-ocr/tessdata
2. Place `.traineddata` files in:
   - `C:\Program Files\Tesseract-OCR\tessdata\`
3. Configure in `.env`:
   ```
   OCR_LANGUAGES=eng,spa,fra  # English, Spanish, French
   ```

## Verification

Once installed, you should see:
```
✅ Tesseract found at: C:\Program Files\Tesseract-OCR\tesseract.exe
✅ Tesseract OCR is available
```

## Next Steps

After successful installation:
1. Place scanned PDFs or images in `/documents` folder
2. Run the full test suite:
   ```bash
   cd ai
   python tests\test_ocr.py
   ```
3. Start using OCR functionality in your application!

