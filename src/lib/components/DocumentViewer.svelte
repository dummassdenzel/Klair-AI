<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import type { IndexedDocument } from '$lib/api/types';
  import apiClient from '$lib/api/client';

  let { document: doc } = $props<{ document: IndexedDocument }>();

  let container: HTMLDivElement | null = null;
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let contentUrl = $state<string | null>(null);

  // Lazy load PDF.js and mammoth only when needed (client-side)
  let pdfjsLib: any = null;
  let mammoth: any = null;

  // Track the current document ID to detect changes
  let currentDocId = $state<number | null>(null);

  async function loadPDFLib() {
    if (typeof window === 'undefined') return null;
    
    if (!pdfjsLib) {
      const pdfjsModule = await import('pdfjs-dist');
      // pdfjs-dist exports as namespace, so use the module directly
      pdfjsLib = pdfjsModule;
      
      // Use Vite's ?url syntax to import the worker file
      // This will give us the correct URL that Vite can serve
      try {
        const workerModule = await import('pdfjs-dist/build/pdf.worker.min.mjs?url');
        pdfjsLib.GlobalWorkerOptions.workerSrc = workerModule.default;
      } catch (e) {
        // Fallback: use unpkg CDN instead of cdnjs
        console.warn('Local worker failed, using unpkg CDN:', e);
        pdfjsLib.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.mjs`;
      }
    }
    return pdfjsLib;
  }

  async function loadMammoth() {
    if (typeof window === 'undefined') return null;
    
    if (!mammoth) {
      const mammothModule = await import('mammoth');
      // mammoth exports as default
      mammoth = mammothModule.default || mammothModule;
    }
    return mammoth;
  }

  onMount(async () => {
    if (doc) {
      currentDocId = doc.id;
      await loadDocument();
    }
  });

  // Watch for document prop changes and reload when it changes
  $effect(() => {
    if (doc && doc.id !== currentDocId) {
      currentDocId = doc.id;
      loadDocument();
    }
  });

  onDestroy(() => {
    // Cleanup: revoke object URL if created
    if (contentUrl) {
      URL.revokeObjectURL(contentUrl);
    }
  });

  async function loadDocument() {
    if (!doc) return;
    
    isLoading = true;
    error = null;

    // Cleanup previous content URL before loading new document
    if (contentUrl) {
      URL.revokeObjectURL(contentUrl);
      contentUrl = null;
    }

    // Clear container
    if (container) {
      container.innerHTML = '';
    }

    try {
      const response = await apiClient.get(`/documents/${doc.id}/file`, {
        responseType: 'blob'
      });
      
      const blob = response.data;
      // Normalize file type: remove leading dot if present (e.g., ".pdf" -> "pdf")
      const fileType = doc.file_type.toLowerCase().replace(/^\./, '');

      if (fileType === 'pdf') {
        await renderPDF(blob);
      } else if (fileType === 'docx') {
        await renderDOCX(blob);
      } else if (fileType === 'txt') {
        await renderTXT(blob);
      } else {
        throw new Error(`Unsupported file type: ${fileType}`);
      }

      isLoading = false;
    } catch (err) {
      console.error('Error loading document:', err);
      error = err instanceof Error ? err.message : 'Failed to load document';
      isLoading = false;
    }
  }

  async function renderPDF(blob: Blob) {
    if (!container || typeof window === 'undefined') return;

    // Load PDF.js library first
    const pdfLib = await loadPDFLib();
    if (!pdfLib) {
      throw new Error('PDF.js library could not be loaded');
    }

    // Create object URL for PDF blob (for cleanup)
    const url = URL.createObjectURL(blob);
    contentUrl = url;

    try {
      // Use data loading instead of URL to avoid CORS/worker issues
      const arrayBuffer = await blob.arrayBuffer();
      const loadingTask = pdfLib.getDocument({ data: arrayBuffer });
      const pdf = await loadingTask.promise;

      // Clear container
      container.innerHTML = '';

      // Create PDF viewer container
      const viewerContainer = window.document.createElement('div');
      viewerContainer.className = 'pdf-viewer-container';
      viewerContainer.style.cssText = 'width: 100%; height: 100%; overflow-y: auto;';

      // Render each page
      for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
        const page = await pdf.getPage(pageNum);
        const viewport = page.getViewport({ scale: 1.5 });

        const pageDiv = window.document.createElement('div');
        pageDiv.className = 'pdf-page';
        pageDiv.style.cssText = `
          margin-bottom: 20px;
          border: 1px solid #e5e7eb;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        `;

        const canvas = window.document.createElement('canvas');
        const context = canvas.getContext('2d');
        if (!context) {
          throw new Error('Could not get canvas context');
        }
        
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        await page.render({
          canvasContext: context,
          viewport: viewport,
          canvas: canvas
        }).promise;

        pageDiv.appendChild(canvas);
        viewerContainer.appendChild(pageDiv);
      }

      container.appendChild(viewerContainer);
    } catch (err) {
      throw new Error(`Failed to render PDF: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  }

  async function renderDOCX(blob: Blob) {
    if (!container || typeof window === 'undefined') return;

    // Load mammoth library first
    const mammothLib = await loadMammoth();
    if (!mammothLib) {
      throw new Error('Mammoth library could not be loaded');
    }

    try {
      const arrayBuffer = await blob.arrayBuffer();
      const result = await mammothLib.convertToHtml({ arrayBuffer });

      container.innerHTML = `
        <div class="docx-viewer" style="
          padding: 40px;
          max-width: 900px;
          margin: 0 auto;
          background: white;
          font-family: 'Inter', sans-serif;
          line-height: 1.6;
          color: #37352F;
        ">
          ${result.value}
        </div>
      `;

      // Log any warnings
      if (result.messages.length > 0) {
        console.warn('DOCX conversion warnings:', result.messages);
      }
    } catch (err) {
      throw new Error(`Failed to render DOCX: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  }

  async function renderTXT(blob: Blob) {
    if (!container) return;

    try {
      const text = await blob.text();
      
      container.innerHTML = `
        <div class="text-viewer" style="
          padding: 40px;
          max-width: 900px;
          margin: 0 auto;
          background: white;
          font-family: 'Inter', monospace;
          line-height: 1.8;
          color: #37352F;
          white-space: pre-wrap;
          word-wrap: break-word;
        ">
          ${escapeHtml(text)}
        </div>
      `;
    } catch (err) {
      throw new Error(`Failed to render text: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  }

  function escapeHtml(text: string): string {
    const div = window.document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
</script>

<div class="document-viewer-content h-full overflow-y-auto bg-gray-50" bind:this={container}>
  {#if isLoading}
    <div class="flex items-center justify-center h-full min-h-[400px]">
      <div class="text-center">
        <svg class="animate-spin h-8 w-8 text-[#443C68] mx-auto mb-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <p class="text-gray-600 font-medium">Loading document...</p>
        <p class="text-sm text-gray-500 mt-1">{doc?.file_path?.split('\\').pop() || doc?.file_path?.split('/').pop() || 'Document'}</p>
      </div>
    </div>
  {:else if error}
    <div class="flex items-center justify-center h-full min-h-[400px]">
      <div class="text-center text-red-600">
        <svg class="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
        </svg>
        <p class="font-medium">Error loading document</p>
        <p class="text-sm mt-2">{error}</p>
      </div>
    </div>
  {/if}
</div>

<style>
  :global(.pdf-viewer-container) {
    padding: 20px;
    background: #f5f5f5;
  }

  :global(.pdf-page) {
    background: white;
    margin: 0 auto;
  }
</style>

