<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import type { IndexedDocument } from '$lib/api/types';
    import apiClient from '$lib/api/client';
  
    let { document: doc, searchText = '', pageNumber = null } = $props<{
      document: IndexedDocument;
      searchText?: string;
      pageNumber?: number | null;
    }>();

    let container: HTMLDivElement | null = null;
    let contentContainer: HTMLDivElement | null = null;
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let contentUrl = $state<string | null>(null);

    // Zoom state — only shown for PDF/PPTX/DOCX-as-PDF
    let currentPdfBlob: Blob | null = null;
    let zoomLevel = $state(1.0);
    let canZoom = $state(false);

    // Excel cell editing state
    let isExcelMode = $state(false);
    // Map key: "sheetName::cellAddress", value: {sheet, cell, value}
    let excelChanges = new Map<string, {sheet: string, cell: string, value: string}>();
    let excelHasChanges = $state(false);
    let excelIsSaving = $state(false);
    let excelSaveError = $state<string | null>(null);
    let excelSaveSuccess = $state(false);
    let excelDblClickListener: ((e: MouseEvent) => void) | null = null;

    // Edit mode (TipTap) — only for txt
    let isEditMode = $state(false);
    let editorEl: HTMLDivElement | null = null;
    let tiptapEditor: any = null;
    let hasUnsavedChanges = $state(false);
    let isSaving = $state(false);
    let saveError = $state<string | null>(null);
    let saveSuccess = $state(false);

    // Lazy load PDF.js, mammoth, and xlsx only when needed (client-side)
    let pdfjsLib: any = null;
    let mammoth: any = null;
    let xlsxLib: any = null;

    // Track the current document ID to detect changes
    let currentDocId = $state<number | null>(null);

    // Only TXT gets TipTap editing — DOCX round-trip (mammoth→TipTap→python-docx)
    // is lossy (images, complex formatting dropped). DOCX edits go through AI proposals.
    const EDITABLE_TYPES = new Set(['txt']);
  
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
  
    async function loadXLSX() {
      if (typeof window === 'undefined') return null;
      
      if (!xlsxLib) {
        const xlsxModule = await import('xlsx');
        // xlsx exports as namespace
        xlsxLib = xlsxModule;
      }
      return xlsxLib;
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
      if (contentUrl) URL.revokeObjectURL(contentUrl);
      destroyEditor();
    });
  
     async function loadDocument() {
       if (!doc) return;
       
       isLoading = true;
       error = null;
       canZoom = false;
       zoomLevel = 1.0;
       currentPdfBlob = null;
       saveError = null;
       saveSuccess = false;
       hasUnsavedChanges = false;
       isEditMode = false;
       destroyEditor();
       isExcelMode = false;
       excelChanges.clear();
       excelHasChanges = false;
       excelSaveError = null;
       excelSaveSuccess = false;
       if (excelDblClickListener && contentContainer) {
         contentContainer.removeEventListener('dblclick', excelDblClickListener);
         excelDblClickListener = null;
       }

       // Cleanup previous content URL before loading new document
       if (contentUrl) {
         URL.revokeObjectURL(contentUrl);
         contentUrl = null;
       }
   
       // DON'T clear container here - keep loading spinner visible
       // Container will be cleared inside renderPDF/renderDOCX etc. when ready to render
 
       try {
         // Normalize file type: remove leading dot if present (e.g., ".pdf" -> "pdf")
         const fileType = doc.file_type.toLowerCase().replace(/^\./, '');
 
         // PPTX and DOCX: convert to PDF via LibreOffice for pixel-perfect rendering.
         // Falls back to mammoth (DOCX) if LibreOffice is unavailable (503).
         if (fileType === 'pptx' || fileType === 'docx') {
           try {
             const previewResponse = await apiClient.get(`/documents/${doc.id}/preview?format=pdf`, {
               responseType: 'blob'
             });
             await renderPDF(previewResponse.data);
           } catch (previewErr: any) {
             if (fileType === 'docx' && (previewErr?.response?.status === 503 || previewErr?.response?.status === 400)) {
               // LibreOffice not available — fall back to mammoth HTML rendering
               const response = await apiClient.get(`/documents/${doc.id}/file`, { responseType: 'blob' });
               await renderDOCX(response.data);
             } else {
               throw previewErr;
             }
           }
         } else {
           // For other file types, use the regular file endpoint
           const response = await apiClient.get(`/documents/${doc.id}/file`, {
             responseType: 'blob'
           });

           const blob = response.data;

           if (fileType === 'pdf') {
             await renderPDF(blob);
           } else if (fileType === 'txt') {
             await renderTXT(blob);
           } else if (fileType === 'xlsx' || fileType === 'xls') {
             await renderExcel(blob);
           } else {
             throw new Error(`Unsupported file type: ${fileType}`);
           }
         }
   
         isLoading = false;
       } catch (err) {
         console.error('Error loading document:', err);
         
         // Check if it's a LibreOffice-related error for PPTX
         const fileType = doc.file_type.toLowerCase().replace(/^\./, '');
         if (fileType === 'pptx') {
           const errorMsg = err instanceof Error ? err.message : 'Failed to load PPTX preview';
           if (errorMsg.includes('LibreOffice') || errorMsg.includes('not available') || errorMsg.includes('503')) {
             error = 'PPTX preview requires LibreOffice to be installed on the server.';
           } else {
             error = errorMsg;
           }
         } else {
           error = err instanceof Error ? err.message : 'Failed to load document';
         }
         isLoading = false;
       }
     }
  
     async function renderPDF(blob: Blob) {
       if (!contentContainer || typeof window === 'undefined') return;

       // Store blob so zoom re-renders can reuse it
       currentPdfBlob = blob;

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
   
         // Clear content container
         contentContainer.innerHTML = '';
   
         // Create PDF viewer container
         const viewerContainer = window.document.createElement('div');
         viewerContainer.className = 'pdf-viewer-container';
         viewerContainer.style.cssText = 'width: 100%; overflow-y: auto; padding: 8px 8px 20px; background: #f5f5f5;';

         // Await a frame so the container has been laid out before we measure it.
         // Without this, clientWidth can return 0 on first render, causing pages to render
         // at a fallback 1200px width and then get squished by CSS max-width.
         await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));

         // Get container width for dynamic scaling
         const containerWidth = contentContainer.clientWidth || contentContainer.offsetWidth || 560;
         const maxPageWidth = containerWidth - 32; // 16px padding each side
   
         // Render each page
         for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
           const page = await pdf.getPage(pageNum);
           
           // Get page dimensions at scale 1.0
           const baseViewport = page.getViewport({ scale: 1.0 });
           
           // Calculate scale to fit container width, then apply user zoom
           const scale = Math.min(maxPageWidth / baseViewport.width, 2.0) * zoomLevel;
           const viewport = page.getViewport({ scale });
 
           const pageDiv = window.document.createElement('div');
           pageDiv.className = 'pdf-page';
           pageDiv.dataset.page = String(pageNum);
           pageDiv.style.cssText = `
             position: relative;
             margin: 0 auto 10px auto;
             border: 1px solid #e5e7eb;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1);
             background: white;
             display: block;
             width: ${viewport.width}px;
             height: ${viewport.height}px;
             overflow: hidden;
           `;

           const canvas = window.document.createElement('canvas');
           const context = canvas.getContext('2d');
           if (!context) {
             throw new Error('Could not get canvas context');
           }

           canvas.height = viewport.height;
           canvas.width = viewport.width;
           canvas.style.cssText = 'display: block; width: 100%; height: 100%;';

           await page.render({ canvasContext: context, viewport }).promise;

           pageDiv.appendChild(canvas);

           // Text layer — transparent selectable text over the canvas
           try {
             const textLayerDiv = window.document.createElement('div');
             textLayerDiv.className = 'pdf-text-layer';
             // pdfjs-dist v5 TextLayer
             const TextLayer = pdfLib.TextLayer;
             if (TextLayer) {
               const textLayer = new TextLayer({
                 textContentSource: page.streamTextContent(),
                 container: textLayerDiv,
                 viewport,
               });
               await textLayer.render();
               pageDiv.appendChild(textLayerDiv);
             }
           } catch {
             // Text layer is enhancement-only; ignore if unsupported
           }

           viewerContainer.appendChild(pageDiv);
         }

         contentContainer.appendChild(viewerContainer);
         canZoom = true;

         // Scroll to the target page after render
         if (pageNumber != null) {
           requestAnimationFrame(() => {
             const target = viewerContainer.querySelector<HTMLElement>(`[data-page="${pageNumber}"]`);
             if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
           });
         }
       } catch (err) {
         throw new Error(`Failed to render PDF: ${err instanceof Error ? err.message : 'Unknown error'}`);
       }
     }
  
     async function renderDOCX(blob: Blob) {
       if (!contentContainer || typeof window === 'undefined') return;
  
      // Load mammoth library first
      const mammothLib = await loadMammoth();
      if (!mammothLib) {
        throw new Error('Mammoth library could not be loaded');
      }
  
      try {
         const arrayBuffer = await blob.arrayBuffer();
         const result = await mammothLib.convertToHtml({ arrayBuffer });
 
         contentContainer.innerHTML = `
          <div class="docx-viewer" style="
            padding: 40px;
            max-width: 900px;
            margin: 0 auto;
            background: white;
            font-family: var(--font-sans);
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

        if (searchText) {
          // Defer one tick so the DOM is painted before we search
          requestAnimationFrame(() => scrollToAndHighlight(searchText));
        }
      } catch (err) {
        throw new Error(`Failed to render DOCX: ${err instanceof Error ? err.message : 'Unknown error'}`);
      }
    }
  
   async function renderTXT(blob: Blob) {
     if (!contentContainer) return;
 
     try {
       const text = await blob.text();
       
       contentContainer.innerHTML = `
        <div class="text-viewer" style="
          padding: 40px;
          max-width: 900px;
          margin: 0 auto;
          background: white;
          font-family: var(--font-sans);
          line-height: 1.8;
          color: #37352F;
          white-space: pre-wrap;
          word-wrap: break-word;
        ">
          ${escapeHtml(text)}
        </div>
      `;

      if (searchText) {
        requestAnimationFrame(() => scrollToAndHighlight(searchText));
      }
    } catch (err) {
      throw new Error(`Failed to render text: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  }

     async function renderExcel(blob: Blob) {
       if (!contentContainer || typeof window === 'undefined') return;
  
      // Load xlsx library first
      const xlsx = await loadXLSX();
      if (!xlsx) {
        throw new Error('xlsx library could not be loaded');
      }
  
      try {
        const arrayBuffer = await blob.arrayBuffer();
        // Read with cellStyles to get formatting information
        const workbook = xlsx.read(arrayBuffer, { type: 'array', cellStyles: true });
        
        // Build HTML for all sheets
        let html = '<div class="excel-viewer" style="padding: 40px; max-width: 100%; margin: 0 auto; background: white; font-family: var(--font-sans), sans-serif;">';
        
        // Process each sheet
        workbook.SheetNames.forEach((sheetName: string, index: number) => {
          const worksheet = workbook.Sheets[sheetName];
          
          // Get the range of the worksheet
          const range = xlsx.utils.decode_range(worksheet['!ref'] || 'A1');
          if (!worksheet['!ref']) {
            return; // Skip empty sheets
          }
          
          // Get column widths if available
          const colWidths: { [key: number]: number } = {};
          if (worksheet['!cols']) {
            worksheet['!cols'].forEach((col: any, idx: number) => {
              if (col && col.wpx) {
                colWidths[idx] = col.wpx;
              } else if (col && col.width) {
                // Convert Excel column width to pixels (approximate)
                colWidths[idx] = col.width * 7; // Rough conversion
              }
            });
          }
          
          // Track merged cells
          const mergedCells: { [key: string]: any } = {};
          if (worksheet['!merges']) {
            worksheet['!merges'].forEach((merge: any) => {
              const start = xlsx.utils.encode_cell({ r: merge.s.r, c: merge.s.c });
              mergedCells[start] = {
                rowspan: merge.e.r - merge.s.r + 1,
                colspan: merge.e.c - merge.s.c + 1
              };
            });
          }
          
          // Add sheet header
          if (workbook.SheetNames.length > 1) {
            html += `<div class="excel-sheet-header" style="margin-top: ${index > 0 ? '60px' : '0'}; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #e5e7eb;">`;
            html += `<h2 style="font-size: 24px; font-weight: 600; color: #37352F; margin: 0;">${escapeHtml(sheetName)}</h2>`;
            html += `</div>`;
          }
          
          // Create table
          html += '<div class="excel-table-container" style="overflow-x: auto; margin-bottom: 30px;">';
          html += '<table class="excel-table" style="border-collapse: collapse; background: white; table-layout: fixed;">';
          
          // Build column width styles
          if (Object.keys(colWidths).length > 0) {
            html += '<colgroup>';
            for (let c = range.s.c; c <= range.e.c; c++) {
              const width = colWidths[c] ? `${colWidths[c]}px` : 'auto';
              html += `<col style="width: ${width};" />`;
            }
            html += '</colgroup>';
          }
          
          // Process each row
          for (let r = range.s.r; r <= range.e.r; r++) {
            let rowHasContent = false;
            // Check if row has any content
            for (let c = range.s.c; c <= range.e.c; c++) {
              const cellAddress = xlsx.utils.encode_cell({ r, c });
              const cell = worksheet[cellAddress];
              if (cell && (cell.v !== null && cell.v !== undefined && cell.v !== '')) {
                rowHasContent = true;
                break;
              }
            }
            
            if (!rowHasContent) continue;
            
            html += '<tr>';
            
            for (let c = range.s.c; c <= range.e.c; c++) {
              const cellAddress = xlsx.utils.encode_cell({ r, c });
              const cell = worksheet[cellAddress];
              const mergeInfo = mergedCells[cellAddress];
              
              // Check if this cell is covered by another merge (not the starting cell)
              let isCoveredByMerge = false;
              if (!mergeInfo) {
                for (const [startAddr, merge] of Object.entries(mergedCells)) {
                  const start = xlsx.utils.decode_cell(startAddr);
                  if (r >= start.r && r <= start.r + (merge as any).rowspan - 1 &&
                      c >= start.c && c <= start.c + (merge as any).colspan - 1 &&
                      !(r === start.r && c === start.c)) {
                    isCoveredByMerge = true;
                    break;
                  }
                }
              }
              
              if (isCoveredByMerge) {
                continue; // Skip this cell, it's covered by a merge
              }
              
              // Get cell value with proper formatting
              let cellValue = '';
              if (cell) {
                if (cell.w !== undefined && cell.w !== null) {
                  cellValue = String(cell.w); // Formatted text (preferred)
                } else if (cell.v !== undefined && cell.v !== null) {
                  // Format numbers with proper decimal places if it's a number
                  if (typeof cell.v === 'number') {
                    // Check if it's an integer or has decimals
                    if (cell.v % 1 === 0) {
                      cellValue = String(cell.v);
                    } else {
                      // Preserve reasonable decimal places
                      cellValue = cell.v.toFixed(2).replace(/\.?0+$/, '');
                    }
                  } else {
                    cellValue = String(cell.v);
                  }
                }
              }
              
              // Build cell style
              const styles: string[] = [];
              
              // Base styles
              styles.push('padding: 8px 12px');
              styles.push('border: 1px solid #d1d5db');
              styles.push('vertical-align: middle');
              
              // Apply cell formatting
              if (cell && cell.s) {
                const style = cell.s;
                
                // Background color
                if (style.fill && style.fill.fgColor) {
                  const bgColor = excelColorToCSS(style.fill.fgColor);
                  if (bgColor) {
                    styles.push(`background-color: ${bgColor}`);
                  }
                }
                
                // Font styles
                if (style.font) {
                  if (style.font.bold) {
                    styles.push('font-weight: bold');
                  }
                  if (style.font.italic) {
                    styles.push('font-style: italic');
                  }
                  if (style.font.underline) {
                    styles.push('text-decoration: underline');
                  }
                  if (style.font.strike) {
                    styles.push('text-decoration: line-through');
                  }
                  if (style.font.sz) {
                    styles.push(`font-size: ${style.font.sz}pt`);
                  }
                  if (style.font.color) {
                    const textColor = excelColorToCSS(style.font.color);
                    if (textColor) {
                      styles.push(`color: ${textColor}`);
                    }
                  }
                  if (style.font.name) {
                    styles.push(`font-family: "${style.font.name}", sans-serif`);
                  }
                }
                
                // Alignment
                if (style.alignment) {
                  if (style.alignment.horizontal) {
                    styles.push(`text-align: ${style.alignment.horizontal}`);
                  }
                  if (style.alignment.vertical) {
                    styles.push(`vertical-align: ${style.alignment.vertical}`);
                  }
                  if (style.alignment.wrapText) {
                    styles.push('white-space: normal');
                    styles.push('word-wrap: break-word');
                  }
                }
                
                // Borders
                if (style.border) {
                  const borderStyles = getBorderStyles(style.border);
                  if (borderStyles.length > 0) {
                    styles.push(...borderStyles);
                  }
                }
              }
              
              // Merge attributes
              let mergeAttrs = '';
              if (mergeInfo) {
                if (mergeInfo.rowspan > 1) {
                  mergeAttrs += ` rowspan="${mergeInfo.rowspan}"`;
                }
                if (mergeInfo.colspan > 1) {
                  mergeAttrs += ` colspan="${mergeInfo.colspan}"`;
                }
              }
              
              const cellStyle = styles.join('; ');
              html += `<td style="${cellStyle}"${mergeAttrs} data-sheet="${escapeAttr(sheetName)}" data-cell="${cellAddress}" data-original-value="${escapeAttr(cellValue)}">${escapeHtml(cellValue)}</td>`;
            }
            
            html += '</tr>';
          }
          
          html += '</table>';
          html += '</div>';
        });
        
         html += '</div>';

         contentContainer.innerHTML = html;

         // Enable cell editing for xlsx (xls is read-only via xlrd)
         const excelFileType = doc?.file_type?.toLowerCase().replace(/^\./, '');
         if (excelFileType === 'xlsx') {
           isExcelMode = true;
           excelDblClickListener = (e: MouseEvent) => handleExcelCellDblClick(e);
           contentContainer.addEventListener('dblclick', excelDblClickListener);
         }
      } catch (err) {
        throw new Error(`Failed to render Excel: ${err instanceof Error ? err.message : 'Unknown error'}`);
      }
    }
  
    // Convert Excel color format to CSS color
    function excelColorToCSS(color: any): string | null {
      if (!color) return null;
      
      // RGB format
      if (color.rgb) {
        // Remove alpha if present (Excel uses ARGB, CSS uses RGB)
        const rgb = color.rgb;
        if (rgb.length === 8) {
          // ARGB format, remove alpha
          return `#${rgb.substring(2)}`;
        }
        return `#${rgb}`;
      }
      
      // Theme color (limited support)
      if (color.theme !== undefined) {
        // Basic theme color mapping
        const themeColors: { [key: number]: string } = {
          0: '#000000', // Dark 1
          1: '#FFFFFF', // Light 1
          2: '#FF0000', // Dark 2
          3: '#00FF00', // Light 2
          4: '#0000FF', // Accent 1
          5: '#FFFF00', // Accent 2
          6: '#FF00FF', // Accent 3
          7: '#00FFFF', // Accent 4
          8: '#800000', // Accent 5
          9: '#008000', // Accent 6
        };
        return themeColors[color.theme] || null;
      }
      
      return null;
    }
  
    // Get border styles from Excel border format
    function getBorderStyles(border: any): string[] {
      const styles: string[] = [];
      
      const borderProps = ['top', 'right', 'bottom', 'left'] as const;

      borderProps.forEach((side) => {
        const borderSide = border[side];
        if (borderSide && borderSide.style) {
          const color = borderSide.color ? excelColorToCSS(borderSide.color) : '#d1d5db';
          const style = borderSide.style === 'thin' ? '1px solid' :
                       borderSide.style === 'medium' ? '2px solid' :
                       borderSide.style === 'thick' ? '3px solid' :
                       borderSide.style === 'dashed' ? '1px dashed' :
                       borderSide.style === 'dotted' ? '1px dotted' :
                       '1px solid';
          styles.push(`border-${side}: ${style} ${color || '#d1d5db'}`);
        }
      });
      
      return styles;
    }
  
    function escapeHtml(text: string): string {
      const div = window.document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    function escapeAttr(val: string): string {
      return val.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    }

    /**
     * Find the first occurrence of `snippet` in the rendered document and
     * scroll to it with a highlight.
     *
     * For PDF text layers: add a CSS class to the matching span (no DOM mutation).
     * For DOCX/TXT (mammoth HTML): wrap in <mark> via a Range (TreeWalker).
     */
    // ------------------------------------------------------------------
    // Edit mode — TipTap
    // ------------------------------------------------------------------

    function destroyEditor() {
      if (tiptapEditor) {
        try { tiptapEditor.destroy(); } catch { /* ignore */ }
        tiptapEditor = null;
      }
    }

    async function enterEditMode() {
      if (!doc || typeof window === 'undefined') return;
      const fileType = doc.file_type.toLowerCase().replace(/^\./, '');
      if (!EDITABLE_TYPES.has(fileType)) return;

      isEditMode = true;
      hasUnsavedChanges = false;
      saveError = null;
      saveSuccess = false;

      // Wait a tick for editorEl to be in the DOM
      await new Promise<void>(r => requestAnimationFrame(() => r()));
      if (!editorEl) return;

      let initialHTML = '';

      try {
        const response = await apiClient.get(`/documents/${doc.id}/file`, { responseType: 'blob' });
        const text = await (response.data as Blob).text();
        // Wrap each line as a paragraph so TipTap renders it correctly
        initialHTML = text
          .split('\n')
          .map(line => `<p>${escapeHtml(line) || '<br>'}</p>`)
          .join('');
      } catch (e) {
        console.error('Failed to load content for editing:', e);
        initialHTML = '<p></p>';
      }

      // Lazy-load TipTap
      const { Editor } = await import('@tiptap/core');
      const { default: StarterKit } = await import('@tiptap/starter-kit');
      const { Placeholder } = await import('@tiptap/extension-placeholder');

      destroyEditor();

      tiptapEditor = new Editor({
        element: editorEl,
        extensions: [
          StarterKit,
          Placeholder.configure({ placeholder: 'Start typing…' }),
        ],
        content: initialHTML,
        onUpdate: () => { hasUnsavedChanges = true; },
      });
    }

    function exitEditMode() {
      destroyEditor();
      isEditMode = false;
      hasUnsavedChanges = false;
      saveError = null;
      saveSuccess = false;
    }

    async function saveDocument() {
      if (!tiptapEditor || !doc) return;
      isSaving = true;
      saveError = null;
      saveSuccess = false;

      const fileType = doc.file_type.toLowerCase().replace(/^\./, '');
      const html = tiptapEditor.getHTML();

      // For TXT, extract plain text from the editor
      const content = fileType === 'txt' ? tiptapEditor.getText({ blockSeparator: '\n' }) : html;

      try {
        await apiClient.post('/documents/edit/save-content', {
          file_path: doc.file_path,
          content,
          fmt: fileType as 'txt' | 'docx',
        });
        hasUnsavedChanges = false;
        saveSuccess = true;
        setTimeout(() => { saveSuccess = false; }, 3000);
      } catch (e: any) {
        saveError = e?.response?.data?.detail ?? 'Save failed. Please try again.';
      } finally {
        isSaving = false;
      }
    }

    // ------------------------------------------------------------------
    // Excel cell editing
    // ------------------------------------------------------------------

    function handleExcelCellDblClick(e: MouseEvent) {
      const td = (e.target as HTMLElement).closest('td[data-cell]') as HTMLTableCellElement | null;
      if (!td || td.dataset.editing) return;

      const sheetName  = td.dataset.sheet ?? '';
      const cellAddr   = td.dataset.cell  ?? '';
      const origValue  = td.dataset.originalValue ?? '';
      // Use the last-saved value for the input (may differ from originalValue after edits)
      const currentVal = td.dataset.currentValue ?? origValue;

      td.dataset.editing = 'true';
      td.textContent = '';

      const input = window.document.createElement('input');
      input.type = 'text';
      input.value = currentVal;
      input.className = 'cell-inline-input';

      let committed = false;
      const commit = () => {
        if (committed) return;
        committed = true;
        delete td.dataset.editing;
        const newVal = input.value;
        td.textContent = newVal;
        td.dataset.currentValue = newVal;

        const key = `${sheetName}::${cellAddr}`;
        if (newVal !== origValue) {
          excelChanges.set(key, { sheet: sheetName, cell: cellAddr, value: newVal });
          td.style.backgroundColor = '#fef3c7';
        } else {
          excelChanges.delete(key);
          td.style.backgroundColor = '';
        }
        excelHasChanges = excelChanges.size > 0;
      };

      input.addEventListener('blur', commit);
      input.addEventListener('keydown', (ke: KeyboardEvent) => {
        if (ke.key === 'Enter')  { ke.preventDefault(); input.blur(); }
        if (ke.key === 'Escape') { input.value = currentVal; input.blur(); }
        if (ke.key === 'Tab')    { ke.preventDefault(); input.blur(); }
      });

      td.appendChild(input);
      requestAnimationFrame(() => { input.focus(); input.select(); });
    }

    async function saveExcelCells() {
      if (!doc || excelChanges.size === 0) return;
      excelIsSaving = true;
      excelSaveError = null;
      excelSaveSuccess = false;

      const changes = Array.from(excelChanges.values());
      try {
        await apiClient.post('/documents/edit/save-cells', {
          file_path: doc.file_path,
          changes,
        });
        // Update originalValue on saved cells and flash green
        if (contentContainer) {
          for (const change of changes) {
            const tds = contentContainer.querySelectorAll<HTMLTableCellElement>('td[data-cell]');
            for (const td of tds) {
              if (td.dataset.sheet === change.sheet && td.dataset.cell === change.cell) {
                td.dataset.originalValue = change.value;
                td.style.backgroundColor = '#d1fae5';
                const el = td;
                setTimeout(() => { el.style.backgroundColor = ''; }, 2000);
              }
            }
          }
        }
        excelChanges.clear();
        excelHasChanges = false;
        excelSaveSuccess = true;
        setTimeout(() => { excelSaveSuccess = false; }, 3000);
      } catch (e: any) {
        excelSaveError = e?.response?.data?.detail ?? 'Save failed. Please try again.';
      } finally {
        excelIsSaving = false;
      }
    }

    async function discardExcelChanges() {
      excelChanges.clear();
      excelHasChanges = false;
      excelSaveError = null;
      await loadDocument();
    }

    async function adjustZoom(delta: number) {
      if (!currentPdfBlob) return;
      const next = Math.max(0.5, Math.min(3.0, zoomLevel + delta));
      if (next === zoomLevel) return;
      zoomLevel = next;
      await renderPDF(currentPdfBlob);
    }

    function scrollToAndHighlight(snippet: string) {
      if (!contentContainer || !snippet) return;
      const needle = snippet.slice(0, 80).trim().toLowerCase();
      if (!needle) return;

      // --- PDF text layer path ---
      // Clear any previous highlights first
      contentContainer.querySelectorAll('.pdf-text-layer span.klair-highlight').forEach(
        (el) => el.classList.remove('klair-highlight')
      );

      const textLayerSpans = Array.from(
        contentContainer.querySelectorAll<HTMLSpanElement>('.pdf-text-layer span')
      );
      if (textLayerSpans.length > 0) {
        // Try progressively shorter prefixes to handle fragmented text items
        for (const prefixLen of [needle.length, Math.min(40, needle.length), Math.min(20, needle.length)]) {
          const prefix = needle.slice(0, prefixLen);
          for (const span of textLayerSpans) {
            if ((span.textContent ?? '').toLowerCase().includes(prefix)) {
              span.classList.add('klair-highlight');
              span.scrollIntoView({ behavior: 'smooth', block: 'center' });
              return;
            }
          }
        }
        // No span matched — page-level scroll already handled by renderPDF
        return;
      }

      // --- DOCX/TXT mammoth path (TreeWalker + Range) ---
      const walker = document.createTreeWalker(contentContainer, NodeFilter.SHOW_TEXT);
      let node: Node | null;
      while ((node = walker.nextNode())) {
        const text = node.textContent ?? '';
        const idx = text.toLowerCase().indexOf(needle);
        if (idx === -1) continue;
        try {
          const range = document.createRange();
          range.setStart(node, idx);
          range.setEnd(node, idx + needle.length);
          const mark = document.createElement('mark');
          mark.className = 'klair-highlight';
          range.surroundContents(mark);
          mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } catch {
          (node.parentElement ?? contentContainer).scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        return;
      }
    }
  </script>
  
  <div class="document-viewer-content h-full flex flex-col bg-gray-50 relative" bind:this={container}>

    <!-- Edit mode toolbar -->
    {#if isEditMode}
      <div class="edit-toolbar">
        <!-- Formatting buttons -->
        <div class="edit-toolbar-group">
          <button type="button" class="fmt-btn" title="Bold (Ctrl+B)"
            onclick={() => tiptapEditor?.chain().focus().toggleBold().run()}
            class:active={tiptapEditor?.isActive('bold')}>
            <strong>B</strong>
          </button>
          <button type="button" class="fmt-btn" title="Italic (Ctrl+I)"
            onclick={() => tiptapEditor?.chain().focus().toggleItalic().run()}
            class:active={tiptapEditor?.isActive('italic')}>
            <em>I</em>
          </button>
          <button type="button" class="fmt-btn" title="Strikethrough"
            onclick={() => tiptapEditor?.chain().focus().toggleStrike().run()}
            class:active={tiptapEditor?.isActive('strike')}>
            <s>S</s>
          </button>
        </div>
        <div class="edit-toolbar-divider"></div>
        <div class="edit-toolbar-group">
          <button type="button" class="fmt-btn" title="Heading 1"
            onclick={() => tiptapEditor?.chain().focus().toggleHeading({ level: 1 }).run()}
            class:active={tiptapEditor?.isActive('heading', { level: 1 })}>H1</button>
          <button type="button" class="fmt-btn" title="Heading 2"
            onclick={() => tiptapEditor?.chain().focus().toggleHeading({ level: 2 }).run()}
            class:active={tiptapEditor?.isActive('heading', { level: 2 })}>H2</button>
          <button type="button" class="fmt-btn" title="Bullet list"
            onclick={() => tiptapEditor?.chain().focus().toggleBulletList().run()}
            class:active={tiptapEditor?.isActive('bulletList')}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="9" y1="6" x2="20" y2="6"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="18" x2="20" y2="18"/><circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none"/><circle cx="4" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="4" cy="18" r="1.5" fill="currentColor" stroke="none"/></svg>
          </button>
          <button type="button" class="fmt-btn" title="Ordered list"
            onclick={() => tiptapEditor?.chain().focus().toggleOrderedList().run()}
            class:active={tiptapEditor?.isActive('orderedList')}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="10" y1="6" x2="21" y2="6"/><line x1="10" y1="12" x2="21" y2="12"/><line x1="10" y1="18" x2="21" y2="18"/><path d="M4 6h1v4"/><path d="M4 10h2"/><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/></svg>
          </button>
        </div>
        <div class="edit-toolbar-spacer"></div>
        <!-- Status + actions -->
        {#if saveError}
          <span class="edit-status error">{saveError}</span>
        {:else if saveSuccess}
          <span class="edit-status success">Saved</span>
        {:else if hasUnsavedChanges}
          <span class="edit-status unsaved">Unsaved changes</span>
        {/if}
        <button type="button" class="edit-action-btn discard" onclick={exitEditMode} title="Discard changes and close editor">
          Discard
        </button>
        <button type="button" class="edit-action-btn save" onclick={saveDocument} disabled={isSaving || !hasUnsavedChanges} title="Save changes to disk">
          {#if isSaving}Saving…{:else}Save{/if}
        </button>
      </div>
    {/if}

    <!-- Excel hint/save bar -->
    {#if isExcelMode && !isLoading && !error}
      <div class="excel-bar">
        {#if excelSaveError}
          <span class="edit-status error">{excelSaveError}</span>
        {:else if excelSaveSuccess}
          <span class="edit-status success">Saved</span>
        {:else if excelHasChanges}
          <span class="edit-status unsaved">{excelChanges.size} cell{excelChanges.size === 1 ? '' : 's'} modified</span>
        {:else}
          <span class="excel-hint">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            Double-click any cell to edit
          </span>
        {/if}
        <span class="edit-toolbar-spacer"></span>
        {#if excelHasChanges}
          <button type="button" class="edit-action-btn discard" onclick={discardExcelChanges}>Discard</button>
          <button type="button" class="edit-action-btn save" onclick={saveExcelCells} disabled={excelIsSaving}>
            {excelIsSaving ? 'Saving…' : 'Save'}
          </button>
        {/if}
      </div>
    {/if}

    <!-- Zoom toolbar — only for PDF / PPTX / DOCX-as-PDF renders, not in edit mode -->
    {#if canZoom && !isLoading && !error && !isEditMode}
      <div class="zoom-toolbar">
        <button type="button" class="zoom-btn" onclick={() => adjustZoom(-0.25)} title="Zoom out">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
        </button>
        <span class="zoom-label">{Math.round(zoomLevel * 100)}%</span>
        <button type="button" class="zoom-btn" onclick={() => adjustZoom(0.25)} title="Zoom in">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
        </button>
        {#if zoomLevel !== 1.0}
          <button type="button" class="zoom-btn zoom-reset" onclick={() => adjustZoom(1.0 - zoomLevel)} title="Reset zoom">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>
            </svg>
          </button>
        {/if}
      </div>
    {/if}

    <!-- Loading overlay -->
    {#if isLoading}
      <div class="flex items-center justify-center flex-1 min-h-[400px]">
        <div class="text-center">
          <svg class="animate-spin h-8 w-8 text-[#443C68] mx-auto mb-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <p class="text-gray-600 font-medium">Loading document...</p>
          <p class="text-sm text-gray-500 mt-1">{doc?.file_path?.split('\\').pop() || doc?.file_path?.split('/').pop() || 'Document'}</p>
        </div>
      </div>
    {/if}

    <!-- Error message -->
    {#if error && !isLoading}
      <div class="flex items-center justify-center flex-1 min-h-[400px]">
        <div class="text-center text-red-600">
          <svg class="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
          </svg>
          <p class="font-medium">Error loading document</p>
          <p class="text-sm mt-2">{error}</p>
        </div>
      </div>
    {/if}

    <!-- TipTap editor — shown when in edit mode -->
    {#if isEditMode}
      <div class="tiptap-wrapper" bind:this={editorEl}></div>
    {/if}

    <!-- Edit button — visible on hover when loaded, editable type, not in edit mode -->
    {#if !isLoading && !error && !isEditMode && doc && EDITABLE_TYPES.has(doc.file_type.toLowerCase().replace(/^\./, ''))}
      <button
        type="button"
        class="edit-entry-btn"
        onclick={enterEditMode}
        title="Edit document"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        Edit
      </button>
    {/if}

    <!-- Read-only content container — hidden while in edit mode but always bound -->
    <div
      bind:this={contentContainer}
      class="flex-1 overflow-y-auto w-full"
      style={isEditMode || isLoading || error ? 'display:none' : ''}
    ></div>
  </div>
  
   <style>
     :global(.pdf-viewer-container) {
       padding: 8px 8px 20px;
       background: #f5f5f5;
       display: flex;
       flex-direction: column;
       align-items: center;
     }

     :global(.pdf-page) {
       background: white;
       margin: 0 auto;
       display: block;
       overflow: hidden;
     }

     :global(.pdf-page canvas) {
       display: block;
       width: 100%;
       height: 100%;
     }

    /* PDF.js text layer — transparent selectable text over the canvas */
    :global(.pdf-text-layer) {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      overflow: hidden;
      line-height: 1;
      pointer-events: none;
    }

    :global(.pdf-text-layer span) {
      color: transparent;
      position: absolute;
      white-space: pre;
      transform-origin: 0% 0%;
      pointer-events: auto;
      user-select: text;
      cursor: text;
    }

    :global(.pdf-text-layer span.klair-highlight) {
      background-color: rgba(253, 230, 138, 0.55);
      color: rgba(0, 0, 0, 0.75);
      border-radius: 2px;
      scroll-margin-top: 80px;
    }
  
    :global(.excel-viewer) {
      padding: 40px;
      max-width: 100%;
      margin: 0 auto;
      background: white;
      font-family: var(--font-sans);
    }
  
    :global(.excel-sheet-header) {
      margin-top: 60px;
      margin-bottom: 20px;
      padding-bottom: 15px;
      border-bottom: 2px solid #e5e7eb;
    }
  
    :global(.excel-sheet-header:first-child) {
      margin-top: 0;
    }
  
    :global(.excel-table-container) {
      overflow-x: auto;
      margin-bottom: 30px;
    }
  
    :global(.excel-table) {
      width: 100%;
      border-collapse: collapse;
      border: 1px solid #e5e7eb;
      background: white;
    }
  
    :global(.excel-table th) {
      background: #f9fafb;
      font-weight: 600;
      color: #37352F;
      padding: 12px 16px;
      border: 1px solid #e5e7eb;
      text-align: left;
      position: sticky;
      top: 0;
      z-index: 10;
    }
  
    :global(.excel-table td) {
      padding: 10px 16px;
      border: 1px solid #e5e7eb;
      text-align: left;
      color: #37352F;
    }
  
    :global(.excel-table tr:hover) {
      background: #f9fafb;
    }

    :global(.klair-highlight) {
      background-color: #fde68a;
      color: inherit;
      border-radius: 2px;
      padding: 0 1px;
      scroll-margin-top: 80px;
    }

    /* ------------------------------------------------------------------ */
    /* Excel bar + inline cell input                                        */
    /* ------------------------------------------------------------------ */

    .excel-bar {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 5px 12px;
      background: #f9fafb;
      border-bottom: 1px solid #e5e7eb;
      font-size: 12px;
    }

    .excel-hint {
      display: flex;
      align-items: center;
      gap: 5px;
      color: #6b7280;
    }

    :global(.cell-inline-input) {
      display: block;
      width: 100%;
      height: 100%;
      min-width: 60px;
      border: 2px solid #443C68;
      outline: none;
      padding: 3px 6px;
      font-size: inherit;
      font-family: inherit;
      background: white;
      box-sizing: border-box;
      border-radius: 0;
    }

    /* ------------------------------------------------------------------ */
    /* Edit entry button                                                    */
    /* ------------------------------------------------------------------ */

    .edit-entry-btn {
      position: absolute;
      top: 12px;
      right: 12px;
      z-index: 20;
      display: flex;
      align-items: center;
      gap: 5px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 600;
      color: #443C68;
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.15s, box-shadow 0.15s;
      box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    }

    .document-viewer-content:hover .edit-entry-btn {
      opacity: 1;
    }

    .edit-entry-btn:hover {
      background: #f5f3ff;
      border-color: #443C68;
      box-shadow: 0 2px 8px rgba(68,60,104,0.15);
    }

    /* ------------------------------------------------------------------ */
    /* Edit toolbar                                                         */
    /* ------------------------------------------------------------------ */

    .edit-toolbar {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: 2px;
      padding: 6px 10px;
      background: white;
      border-bottom: 1px solid #e5e7eb;
      flex-wrap: wrap;
    }

    .edit-toolbar-group {
      display: flex;
      align-items: center;
      gap: 1px;
    }

    .edit-toolbar-divider {
      width: 1px;
      height: 18px;
      background: #e5e7eb;
      margin: 0 4px;
    }

    .edit-toolbar-spacer {
      flex: 1;
    }

    .fmt-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      min-width: 28px;
      height: 28px;
      padding: 0 6px;
      font-size: 13px;
      border-radius: 5px;
      border: none;
      background: transparent;
      color: #374151;
      cursor: pointer;
      transition: background 0.1s;
    }

    .fmt-btn:hover {
      background: #f3f4f6;
    }

    .fmt-btn.active {
      background: #ede9fe;
      color: #443C68;
    }

    .edit-status {
      font-size: 11px;
      font-weight: 500;
      padding: 2px 8px;
      border-radius: 4px;
      margin-right: 4px;
    }

    .edit-status.unsaved { color: #92400e; background: #fef3c7; }
    .edit-status.success { color: #065f46; background: #d1fae5; }
    .edit-status.error   { color: #991b1b; background: #fee2e2; }

    .edit-action-btn {
      padding: 5px 12px;
      font-size: 12px;
      font-weight: 600;
      border-radius: 6px;
      border: none;
      cursor: pointer;
      transition: background 0.15s, opacity 0.15s;
    }

    .edit-action-btn.discard {
      background: #f3f4f6;
      color: #374151;
    }

    .edit-action-btn.discard:hover {
      background: #e5e7eb;
    }

    .edit-action-btn.save {
      background: #443C68;
      color: white;
      margin-left: 4px;
    }

    .edit-action-btn.save:hover:not(:disabled) {
      background: #5b5190;
    }

    .edit-action-btn.save:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }

    /* ------------------------------------------------------------------ */
    /* TipTap editor wrapper                                                */
    /* ------------------------------------------------------------------ */

    .tiptap-wrapper {
      flex: 1;
      overflow-y: auto;
      background: white;
      padding: 0;
    }

    :global(.tiptap-wrapper .tiptap) {
      min-height: 100%;
      padding: 32px 40px;
      outline: none;
      font-family: var(--font-sans, system-ui, sans-serif);
      font-size: 14px;
      line-height: 1.7;
      color: #37352f;
    }

    :global(.tiptap-wrapper .tiptap p) { margin: 0 0 0.6em; }
    :global(.tiptap-wrapper .tiptap h1) { font-size: 1.75em; font-weight: 700; margin: 1em 0 0.4em; }
    :global(.tiptap-wrapper .tiptap h2) { font-size: 1.35em; font-weight: 600; margin: 0.9em 0 0.35em; }
    :global(.tiptap-wrapper .tiptap h3) { font-size: 1.15em; font-weight: 600; margin: 0.8em 0 0.3em; }
    :global(.tiptap-wrapper .tiptap ul) { padding-left: 1.4em; margin: 0.4em 0; list-style: disc; }
    :global(.tiptap-wrapper .tiptap ol) { padding-left: 1.4em; margin: 0.4em 0; list-style: decimal; }
    :global(.tiptap-wrapper .tiptap li) { margin: 0.15em 0; }
    :global(.tiptap-wrapper .tiptap blockquote) {
      border-left: 3px solid #d1d5db;
      padding-left: 1em;
      color: #6b7280;
      margin: 0.6em 0;
    }
    :global(.tiptap-wrapper .tiptap code) {
      background: #f3f4f6;
      border-radius: 3px;
      padding: 0.1em 0.35em;
      font-size: 0.88em;
      font-family: monospace;
    }
    :global(.tiptap-wrapper .tiptap pre) {
      background: #1e1b2e;
      color: #e2e8f0;
      border-radius: 6px;
      padding: 1em;
      overflow-x: auto;
      margin: 0.6em 0;
    }
    :global(.tiptap-wrapper .tiptap pre code) {
      background: transparent;
      color: inherit;
      padding: 0;
    }
    :global(.tiptap-wrapper .tiptap p.is-editor-empty:first-child::before) {
      content: attr(data-placeholder);
      float: left;
      color: #adb5bd;
      pointer-events: none;
      height: 0;
    }

    .zoom-toolbar {
      position: sticky;
      bottom: 16px;
      left: 50%;
      transform: translateX(-50%);
      width: fit-content;
      display: flex;
      align-items: center;
      gap: 4px;
      background: rgba(30, 27, 46, 0.88);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 999px;
      padding: 6px 12px;
      z-index: 30;
      box-shadow: 0 4px 16px rgba(0,0,0,0.25);
      pointer-events: auto;
    }

    .zoom-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: transparent;
      color: rgba(255,255,255,0.85);
      border: none;
      cursor: pointer;
      transition: background 0.15s;
    }

    .zoom-btn:hover {
      background: rgba(255,255,255,0.12);
      color: white;
    }

    .zoom-label {
      font-size: 12px;
      font-weight: 600;
      color: rgba(255,255,255,0.9);
      min-width: 40px;
      text-align: center;
      user-select: none;
    }

    .zoom-reset {
      color: rgba(253, 230, 138, 0.85);
    }

    .zoom-reset:hover {
      color: #fde68a;
    }
  </style>
  
  