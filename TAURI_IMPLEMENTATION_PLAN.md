# Tauri Desktop App Implementation Plan

## 📋 Overview
This document outlines the strategy for adding a desktop application version using Tauri while maintaining the existing web application.

## 🎯 Goals
1. **Keep web version fully functional** - No breaking changes
2. **Share maximum code** - Reuse components, stores, API clients
3. **Leverage native features** - File system access, notifications, system tray
4. **Single codebase** - Maintain both web and desktop from one repo

---

## 📐 Architecture Strategy

### Option A: Dual Adapter Approach (Recommended)
```
Current: SvelteKit → adapter-auto → Web
Future:  SvelteKit → adapter-static (web) OR adapter-tauri (desktop)
```

**Pros:**
- ✅ Share 100% of frontend code
- ✅ Simple build process
- ✅ Easy to maintain

**Cons:**
- ⚠️ Need conditional logic for platform-specific features

### Option B: Monorepo with Shared Packages
```
klair-ai/
├── packages/
│   ├── shared/          # Shared business logic
│   └── ui/              # Shared components
├── apps/
│   ├── web/             # Web app
│   └── desktop/         # Desktop app
└── ai/                  # Backend (shared)
```

**Pros:**
- ✅ Clear separation
- ✅ Independent versioning
- ✅ Better for large teams

**Cons:**
- ⚠️ More complex setup
- ⚠️ More overhead for small project

---

## 🚀 Recommended Approach: Dual Adapter (Option A)

**Why:** Your project is well-structured and can share code easily. Dual adapter is simpler and sufficient.

---

## 📦 Phase 1: Preparation & Setup

### 1.1 Install Tauri Dependencies
```bash
npm install -D @tauri-apps/cli @tauri-apps/api
npm install -D @sveltejs/adapter-static  # For web builds
```

### 1.2 Install Rust (if not installed)
- Windows: Download from rustup.rs
- Required for Tauri backend compilation

### 1.3 Project Structure (Minimal Changes)
```
klair-ai/
├── src/                    # ✅ Keep as-is (shared)
├── src-tauri/             # 🆕 Tauri backend (Rust)
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   └── src/
│       └── main.rs
├── svelte.config.js       # 🔄 Modify for dual adapters
├── vite.config.ts         # 🔄 Add Tauri plugin
└── package.json           # 🔄 Add Tauri scripts
```

---

## 🔧 Phase 2: Configuration Changes

### 2.1 Update `svelte.config.js`
```javascript
import adapter from '@sveltejs/adapter-auto';
import adapterStatic from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const isTauri = process.env.TAURI_PLATFORM !== undefined;

export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: isTauri 
      ? adapterStatic({ fallback: 'index.html' })
      : adapter()
  }
};
```

### 2.2 Update `vite.config.ts`
```typescript
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { readFileSync } from 'fs';

const isTauri = process.env.TAURI_PLATFORM !== undefined;

export default defineConfig({
  plugins: [sveltekit()],
  clearScreen: false,
  server: {
    port: 1420,
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

### 2.3 Create `src-tauri/tauri.conf.json`
```json
{
  "build": {
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build",
    "devPath": "http://localhost:1420",
    "distDir": "../.svelte-kit/output/client",
    "withGlobalTauri": false
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
        "scope": ["http://127.0.0.1:8000/**", "http://localhost:8000/**"]
      },
      "fs": {
        "all": false,
        "readFile": true,
        "writeFile": false,
        "readDir": true,
        "scope": ["$DOCUMENT/**", "$DESKTOP/**", "$HOME/**"]
      },
      "dialog": {
        "all": false,
        "open": true,
        "save": false
      },
      "notification": {
        "all": true
      }
    },
    "bundle": {
      "active": true,
      "targets": "all",
      "identifier": "com.klair.ai",
      "icon": [
        "icons/32x32.png",
        "icons/128x128.png",
        "icons/128x128@2x.png",
        "icons/icon.icns",
        "icons/icon.ico"
      ]
    },
    "security": {
      "csp": null
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

### 2.4 Update `package.json` Scripts
```json
{
  "scripts": {
    "dev": "vite dev",
    "dev:tauri": "tauri dev",
    "build": "vite build",
    "build:tauri": "tauri build",
    "preview": "vite preview",
    "tauri": "tauri"
  }
}
```

---

## 🔄 Phase 3: Code Adaptations

### 3.1 Platform Detection Utility
Create `src/lib/utils/platform.ts`:
```typescript
export const isTauri = typeof window !== 'undefined' && '__TAURI__' in window;

export const platform = {
  isTauri,
  isWeb: !isTauri,
  name: isTauri ? 'desktop' : 'web'
};
```

### 3.2 API Client Adaptation
Update `src/lib/api/client.ts`:
```typescript
import axios from 'axios';
import { isTauri } from '$lib/utils/platform';

// Use Tauri's HTTP client in desktop, axios in web
const apiClient = isTauri 
  ? createTauriClient()  // Custom Tauri HTTP wrapper
  : axios.create({
      baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api',
      timeout: 30000
    });

// ... rest of client code
```

### 3.3 File System Access (Desktop Enhancement)
Create `src/lib/utils/fileSystem.ts`:
```typescript
import { isTauri } from './platform';
import { open } from '@tauri-apps/api/dialog';
import { readDir } from '@tauri-apps/api/fs';

export async function selectDirectory(): Promise<string | null> {
  if (!isTauri) {
    // Web fallback - use existing modal
    return null;
  }
  
  const selected = await open({
    directory: true,
    multiple: false
  });
  
  return selected as string | null;
}
```

### 3.4 Update Directory Selection
Modify `src/lib/components/DirectorySelectionModal.svelte`:
```svelte
<script>
  import { isTauri } from '$lib/utils/platform';
  import { selectDirectory } from '$lib/utils/fileSystem';
  
  async function handleNativeSelect() {
    if (isTauri) {
      const path = await selectDirectory();
      if (path) {
        dispatch('select', { directoryPath: path });
      }
    }
  }
</script>

{#if isTauri}
  <button onclick={handleNativeSelect}>
    Select Directory (Native)
  </button>
{:else}
  <!-- Existing input field -->
{/if}
```

---

## 🎨 Phase 4: Native Features (Optional Enhancements)

### 4.1 System Tray (Optional)
- Show app icon in system tray
- Quick access menu
- Background operation

### 4.2 Notifications (Optional)
- Notify when documents are indexed
- Alert on errors
- Background processing updates

### 4.3 Auto-start Backend (Optional)
- Bundle Python backend with app
- Auto-start on app launch
- Manage backend process lifecycle

---

## 📝 Phase 5: Build & Distribution

### 5.1 Development
```bash
npm run dev:tauri    # Start Tauri dev mode
```

### 5.2 Production Build
```bash
npm run build:tauri  # Build desktop app
```

### 5.3 Output
- Windows: `.msi` installer
- macOS: `.dmg` or `.app`
- Linux: `.deb` or `.AppImage`

---

## ⚠️ Considerations & Challenges

### Challenge 1: Backend Connection
**Issue:** Desktop app needs to connect to FastAPI backend

**Solutions:**
- **Option A:** Bundle Python backend with app (complex)
- **Option B:** Require backend to be running (current approach)
- **Option C:** Auto-start backend from Tauri (recommended)

### Challenge 2: File System Permissions
**Issue:** Desktop app needs file system access

**Solution:** Configure Tauri allowlist for file operations

### Challenge 3: CORS
**Issue:** Web version has CORS, desktop doesn't need it

**Solution:** Conditional CORS handling in backend

### Challenge 4: Auto-updates
**Issue:** Desktop apps need update mechanism

**Solution:** Use Tauri's built-in updater or external solution

---

## 🗺️ Implementation Timeline

### Week 1: Setup & Configuration
- [ ] Install Tauri dependencies
- [ ] Set up Rust toolchain
- [ ] Configure dual adapters
- [ ] Test basic Tauri app

### Week 2: Code Adaptation
- [ ] Add platform detection
- [ ] Update API client
- [ ] Implement native file dialogs
- [ ] Test all features

### Week 3: Polish & Testing
- [ ] Add native features (optional)
- [ ] Test on all platforms
- [ ] Fix platform-specific issues
- [ ] Create app icons

### Week 4: Build & Distribution
- [ ] Set up build pipeline
- [ ] Create installers
- [ ] Test installation
- [ ] Document distribution process

---

## 📚 Resources

- [Tauri Documentation](https://tauri.app/)
- [SvelteKit Adapters](https://kit.svelte.dev/docs/adapters)
- [Tauri + SvelteKit Guide](https://tauri.app/v1/guides/getting-started/setup/sveltekit)

---

## ✅ Success Criteria

1. ✅ Web version still works perfectly
2. ✅ Desktop app launches and functions
3. ✅ All features work in both versions
4. ✅ Native file dialogs in desktop
5. ✅ Clean build process
6. ✅ No code duplication

---

## 🎯 Next Steps

1. **Review this plan** - Does this approach work for you?
2. **Decide on backend strategy** - Bundle or require running?
3. **Start Phase 1** - Install and configure Tauri
4. **Iterate** - Build incrementally, test frequently

---

## 💡 Questions to Consider

1. **Backend Strategy:** Do you want to bundle the Python backend, or require users to run it separately?
2. **Distribution:** Will you distribute via website, app stores, or both?
3. **Auto-updates:** Do you need automatic update functionality?
4. **Native Features:** Which native features are most important? (file dialogs, notifications, system tray)
5. **Platform Priority:** Windows, macOS, Linux, or all three?

