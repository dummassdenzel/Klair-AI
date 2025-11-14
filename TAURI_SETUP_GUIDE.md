# Tauri Setup Guide - Using `npx tauri init`

## ✅ Recommendation: Use `npx tauri init`

**Why:**
- ✅ Official, tested setup
- ✅ Detects SvelteKit automatically
- ✅ Creates all required files correctly
- ✅ Less error-prone
- ✅ Follows Tauri best practices
- ✅ Can customize after initialization

---

## 🚀 Step-by-Step Setup

### Step 1: Install Tauri CLI (if not already installed)
```bash
npm install -D @tauri-apps/cli @tauri-apps/api
```

### Step 2: Run Tauri Init
```bash
npx tauri init
```

### Step 3: Answer the Prompts

When `npx tauri init` runs, it will ask you questions. Here's what to answer:

#### **1. What is your app name?**
```
Klair AI
```

#### **2. What should the window title be?**
```
Klair AI
```

#### **3. Where are your web assets located?**
```
.svelte-kit/output/client
```
**Important:** This is where SvelteKit outputs the built files. Tauri will use this for production builds.

#### **4. What is the URL of your dev server?**
```
http://localhost:5173
```
**Note:** This is your current Vite dev server port. We'll verify this matches your setup.

#### **5. What is your frontend dev command?**
```
npm run dev
```

#### **6. What is your frontend build command?**
```
npm run build
```

---

## 📝 What `npx tauri init` Creates

After running the command, you'll get:

```
klair-ai/
├── src-tauri/              # 🆕 Created by Tauri
│   ├── Cargo.toml          # Rust dependencies
│   ├── tauri.conf.json     # Tauri configuration
│   ├── src/
│   │   └── main.rs         # Rust entry point
│   └── icons/              # App icons (default)
├── package.json            # 🔄 Updated with Tauri scripts
└── (your existing files)   # ✅ All untouched
```

---

## 🔧 Post-Init Customization

After `npx tauri init` completes, you'll need to customize a few things:

### 1. Update `src-tauri/tauri.conf.json`

The init command creates a basic config. Update it for your needs:

```json
{
  "build": {
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build",
    "devPath": "http://localhost:5173",
    "distDir": "../.svelte-kit/output/client"
  },
  "package": {
    "productName": "Klair AI",
    "version": "0.0.1"
  },
  "tauri": {
    "allowlist": {
      "all": false,
      "shell": {
        "all": false,
        "open": true
      },
      "http": {
        "all": true,
        "request": true,
        "scope": [
          "http://127.0.0.1:8000/**",
          "http://localhost:8000/**"
        ]
      },
      "fs": {
        "all": false,
        "readFile": true,
        "readDir": true,
        "scope": [
          "$DOCUMENT/**",
          "$DESKTOP/**",
          "$HOME/**"
        ]
      },
      "dialog": {
        "all": false,
        "open": true
      }
    },
    "bundle": {
      "active": true,
      "targets": "all",
      "identifier": "com.klair.ai"
    },
    "windows": [
      {
        "fullscreen": false,
        "resizable": true,
        "title": "Klair AI",
        "width": 1200,
        "height": 800,
        "minWidth": 800,
        "minHeight": 600
      }
    ]
  }
}
```

### 2. Update `svelte.config.js` for Dual Adapter

After init, modify your SvelteKit config to support both web and desktop:

```javascript
import adapter from '@sveltejs/adapter-auto';
import adapterStatic from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// Detect if we're building for Tauri
const isTauri = process.env.TAURI_PLATFORM !== undefined;

export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: isTauri 
      ? adapterStatic({ 
          fallback: 'index.html',
          precompress: false,
          strict: false
        })
      : adapter()
  }
};
```

### 3. Install Static Adapter

```bash
npm install -D @sveltejs/adapter-static
```

### 4. Update `vite.config.ts`

Add Tauri-specific configuration:

```typescript
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const isTauri = process.env.TAURI_PLATFORM !== undefined;

export default defineConfig({
  plugins: [sveltekit()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ['**/src-tauri/**']
    }
  },
  envPrefix: ['VITE_', 'TAURI_'],
  build: {
    target: isTauri ? ['es2021', 'chrome100', 'safari13'] : undefined,
    minify: !isTauri ? 'esbuild' : false,
    sourcemap: isTauri
  },
  optimizeDeps: {
    exclude: ['pdfjs-dist']
  },
  worker: {
    format: 'es'
  }
});
```

---

## 🧪 Testing the Setup

### 1. Test Development Mode
```bash
npm run tauri dev
```

This should:
- Start your SvelteKit dev server
- Launch the Tauri desktop window
- Hot reload on changes

### 2. Test Production Build
```bash
npm run tauri build
```

This creates installers in `src-tauri/target/release/bundle/`

---

## ⚠️ Common Issues & Solutions

### Issue 1: Port Already in Use
**Problem:** Port 5173 is already in use

**Solution:** Update `vite.config.ts` to use a different port, or update `tauri.conf.json` devPath

### Issue 2: SvelteKit Build Output Location
**Problem:** Tauri can't find built files

**Solution:** Verify `distDir` in `tauri.conf.json` matches your SvelteKit output:
- SvelteKit default: `.svelte-kit/output/client`
- If using adapter-static: `.svelte-kit/output/client`

### Issue 3: Rust Not Installed
**Problem:** `npx tauri init` fails with Rust errors

**Solution:** Install Rust first:
```bash
# Windows (PowerShell)
Invoke-WebRequest -Uri https://win.rustup.rs/x86_64 -OutFile rustup-init.exe
.\rustup-init.exe

# Or visit: https://rustup.rs/
```

### Issue 4: CORS Errors in Desktop
**Problem:** API calls fail in desktop app

**Solution:** Add your backend URL to `http.scope` in `tauri.conf.json`

---

## 📋 Checklist After Init

- [ ] `src-tauri/` folder created
- [ ] `tauri.conf.json` customized for your app
- [ ] `svelte.config.js` updated for dual adapter
- [ ] `vite.config.ts` updated with Tauri config
- [ ] `@sveltejs/adapter-static` installed
- [ ] `npm run tauri dev` works
- [ ] Web version still works (`npm run dev`)
- [ ] API calls work in desktop app

---

## 🎯 Next Steps After Setup

1. **Add Platform Detection**
   - Create `src/lib/utils/platform.ts`
   - Detect if running in Tauri

2. **Update API Client**
   - Make it work in both web and desktop
   - Handle Tauri's HTTP client if needed

3. **Add Native Features**
   - File dialogs
   - Notifications
   - System tray (optional)

---

## 💡 Why Not Manual Setup?

**Manual setup is error-prone:**
- ❌ Easy to miss required files
- ❌ Configuration mistakes
- ❌ Version mismatches
- ❌ Missing dependencies
- ❌ More time-consuming

**`npx tauri init` is better because:**
- ✅ Official, tested setup
- ✅ Handles all dependencies
- ✅ Creates correct structure
- ✅ Can customize after
- ✅ Follows best practices

---

## 🚀 Ready to Start?

1. Run `npx tauri init`
2. Answer the prompts (use values above)
3. Follow post-init customization
4. Test with `npm run tauri dev`

Good luck! 🎉

