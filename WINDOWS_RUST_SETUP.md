# Fixing Rust Linker Error on Windows

## 🔴 The Problem
```
error: linker `link.exe` not found
note: the msvc targets depend on the msvc linker but `link.exe` was not found
```

This happens because Rust on Windows needs a C++ linker to compile code.

---

## ✅ Solution 1: Install Visual Studio Build Tools (Recommended)

### Step 1: Download Build Tools
1. Go to: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
2. Download **"Build Tools for Visual Studio 2022"** (not the full Visual Studio)

### Step 2: Install
1. Run the installer
2. Select **"Desktop development with C++"** workload
3. Make sure these components are checked:
   - ✅ MSVC v143 - VS 2022 C++ x64/x86 build tools
   - ✅ Windows 10/11 SDK (latest version)
   - ✅ C++ CMake tools for Windows
4. Click **Install**

### Step 3: Restart
- **Close your terminal/IDE completely**
- **Reopen** your terminal/IDE
- Try again: `npm run dev:tauri`

---

## ✅ Solution 2: Use GNU Toolchain (Alternative - No Visual Studio)

If you don't want to install Visual Studio, you can use the GNU toolchain instead.

### Step 1: Install MinGW-w64
1. Download from: https://www.mingw-w64.org/downloads/
   - Or use: https://winlibs.com/ (easier)
2. Extract to `C:\mingw64`
3. Add to PATH: `C:\mingw64\bin`

### Step 2: Configure Rust to Use GNU
```bash
rustup toolchain install stable-x86_64-pc-windows-gnu
rustup default stable-x86_64-pc-windows-gnu
rustup target add x86_64-pc-windows-gnu
```

### Step 3: Create Rust Config
Create file: `C:\Users\YourUsername\.cargo\config.toml`

```toml
[target.x86_64-pc-windows-gnu]
linker = "x86_64-w64-mingw32-gcc"
```

### Step 4: Restart and Try
- Close terminal
- Reopen
- `npm run dev:tauri`

---

## 🎯 Quick Recommendation

**Use Solution 1 (Visual Studio Build Tools)** because:
- ✅ Official Microsoft toolchain
- ✅ Better compatibility
- ✅ Easier setup
- ✅ Works with all Rust projects

**Use Solution 2 (GNU)** only if:
- You can't install Visual Studio
- You prefer open-source tools
- You're already using MinGW

---

## 🧪 After Installing

1. **Close your terminal completely** (important!)
2. **Reopen** your terminal/IDE
3. Verify Rust can find the linker:
   ```bash
   rustc --version
   ```
4. Try Tauri again:
   ```bash
   npm run dev:tauri
   ```

---

## ⚠️ Common Issues

### Issue: "Still can't find link.exe"
**Solution:** 
- Make sure you restarted your terminal
- Check PATH includes Visual Studio tools
- Try: `rustup default stable-x86_64-pc-windows-msvc`

### Issue: "Permission denied"
**Solution:**
- Run terminal as Administrator
- Or install Build Tools as Administrator

### Issue: "Takes too long to install"
**Solution:**
- Build Tools is ~3-6GB download
- This is normal, be patient
- You only need to do this once

---

## 📚 Additional Resources

- [Rust Windows Installation Guide](https://rust-lang.github.io/rustup/installation/windows.html)
- [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
- [Tauri Windows Setup](https://tauri.app/v1/guides/getting-started/prerequisites#windows)


