"""
Tesseract OCR Finder

Helps locate Tesseract OCR installation on Windows.
"""

import os
import platform
import subprocess
from pathlib import Path


def find_tesseract_windows():
    """Find Tesseract on Windows"""
    print("🔍 Searching for Tesseract OCR on Windows...")
    print("=" * 60)
    
    # Common installation paths
    possible_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        r"C:\Tesseract-OCR\tesseract.exe",
    ]
    
    found_paths = []
    
    # Check common paths
    print("\n1️⃣ Checking common installation paths:")
    for path in possible_paths:
        if os.path.exists(path):
            found_paths.append(path)
            print(f"   ✅ Found: {path}")
        else:
            print(f"   ❌ Not found: {path}")
    
    # Check PATH
    print("\n2️⃣ Checking system PATH:")
    try:
        result = subprocess.run(
            ["where", "tesseract.exe"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            path_in_env = result.stdout.strip().split('\n')[0]
            if path_in_env not in found_paths:
                found_paths.append(path_in_env)
            print(f"   ✅ Found in PATH: {path_in_env}")
        else:
            print("   ❌ Not found in PATH")
    except Exception as e:
        print(f"   ⚠️ Could not check PATH: {e}")
    
    # Check Program Files recursively (slow, but thorough)
    print("\n3️⃣ Searching Program Files (this may take a while)...")
    search_dirs = [
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
    ]
    
    for search_dir in search_dirs:
        if search_dir.exists():
            try:
                for tesseract_dir in search_dir.glob("**/Tesseract-OCR"):
                    tesseract_exe = tesseract_dir / "tesseract.exe"
                    if tesseract_exe.exists() and str(tesseract_exe) not in found_paths:
                        found_paths.append(str(tesseract_exe))
                        print(f"   ✅ Found: {tesseract_exe}")
            except Exception as e:
                print(f"   ⚠️ Error searching {search_dir}: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    if found_paths:
        print("✅ Tesseract OCR Found!")
        print("\n📋 Found installation(s):")
        for i, path in enumerate(found_paths, 1):
            print(f"   {i}. {path}")
        
        # Test the first one
        test_path = found_paths[0]
        print(f"\n🧪 Testing: {test_path}")
        try:
            result = subprocess.run(
                [test_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"   ✅ Working! Version: {result.stdout.strip()}")
                print(f"\n💡 Add this to your .env file:")
                print(f"   TESSERACT_PATH={test_path}")
            else:
                print(f"   ⚠️ Found but may not be working correctly")
        except Exception as e:
            print(f"   ⚠️ Could not test: {e}")
    else:
        print("❌ Tesseract OCR Not Found")
        print("\n📥 Installation Instructions:")
        print("   1. Download Tesseract from:")
        print("      https://github.com/UB-Mannheim/tesseract/wiki")
        print("   2. Run the installer")
        print("   3. During installation, check 'Add to PATH' option")
        print("   4. Or manually add to PATH:")
        print("      C:\\Program Files\\Tesseract-OCR")
        print("   5. Restart your terminal/IDE after installation")
        print("\n   Alternative: Set TESSERACT_PATH in .env file after installation")
    
    print("=" * 60)
    return found_paths


def check_tesseract_version(path=None):
    """Check Tesseract version"""
    try:
        if path:
            cmd = [path, "--version"]
        else:
            cmd = ["tesseract", "--version"]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


if __name__ == "__main__":
    system = platform.system()
    
    if system == "Windows":
        find_tesseract_windows()
    else:
        print(f"🔍 Checking for Tesseract on {system}...")
        version = check_tesseract_version()
        if version:
            print(f"✅ Tesseract found: {version}")
            print("   Location: (in system PATH)")
        else:
            print("❌ Tesseract not found")
            if system == "Linux":
                print("   Install: sudo apt-get install tesseract-ocr tesseract-ocr-eng")
            elif system == "Darwin":
                print("   Install: brew install tesseract tesseract-lang")

