<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import type { IndexedDocument } from '$lib/api/types';
    import apiClient from '$lib/api/client';
  
    let { document: doc } = $props<{ document: IndexedDocument }>();
  
    let container: HTMLDivElement | null = null;
    let contentContainer: HTMLDivElement | null = null;
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let contentUrl = $state<string | null>(null);
  
    // Lazy load PDF.js, mammoth, and xlsx only when needed (client-side)
    let pdfjsLib: any = null;
    let mammoth: any = null;
    let xlsxLib: any = null;
  
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
   
       // DON'T clear container here - keep loading spinner visible
       // Container will be cleared inside renderPDF/renderDOCX etc. when ready to render
 
       try {
         // Normalize file type: remove leading dot if present (e.g., ".pdf" -> "pdf")
         const fileType = doc.file_type.toLowerCase().replace(/^\./, '');
 
         // For PPTX files, use the preview endpoint which returns a PDF
         if (fileType === 'pptx') {
           const previewResponse = await apiClient.get(`/documents/${doc.id}/preview?format=pdf`, {
             responseType: 'blob'
           });
           await renderPDF(previewResponse.data);
         } else {
           // For other file types, use the regular file endpoint
           const response = await apiClient.get(`/documents/${doc.id}/file`, {
             responseType: 'blob'
           });
           
           const blob = response.data;
 
           if (fileType === 'pdf') {
             await renderPDF(blob);
           } else if (fileType === 'docx') {
             await renderDOCX(blob);
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
         viewerContainer.style.cssText = 'width: 100%; height: 100%; overflow-y: auto; padding: 20px; background: #f5f5f5;';
   
         // Get container width for dynamic scaling
         const containerWidth = contentContainer.clientWidth || contentContainer.offsetWidth || 1200;
         const maxPageWidth = containerWidth - 80; // Account for padding (20px each side) and margins
   
         // Render each page
         for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
           const page = await pdf.getPage(pageNum);
           
           // Get page dimensions at scale 1.0
           const baseViewport = page.getViewport({ scale: 1.0 });
           
           // Calculate scale to fit container width
           const scale = Math.min(maxPageWidth / baseViewport.width, 2.0); // Max scale of 2.0 for quality
           const viewport = page.getViewport({ scale });
 
           const pageDiv = window.document.createElement('div');
           pageDiv.className = 'pdf-page';
           pageDiv.style.cssText = `
             margin: 0 auto 20px auto;
             border: 1px solid #e5e7eb;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1);
             background: white;
             display: block;
             max-width: 100%;
           `;
 
           const canvas = window.document.createElement('canvas');
           const context = canvas.getContext('2d');
           if (!context) {
             throw new Error('Could not get canvas context');
           }
           
           canvas.height = viewport.height;
           canvas.width = viewport.width;
           canvas.style.cssText = 'display: block; max-width: 100%; height: auto;';
 
           await page.render({
             canvasContext: context,
             viewport: viewport,
             canvas: canvas
           }).promise;
 
           pageDiv.appendChild(canvas);
           viewerContainer.appendChild(pageDiv);
         }
 
         contentContainer.appendChild(viewerContainer);
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
            font-family: 'Poppins', sans-serif;
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
     if (!contentContainer) return;
 
     try {
       const text = await blob.text();
       
       contentContainer.innerHTML = `
        <div class="text-viewer" style="
          padding: 40px;
          max-width: 900px;
          margin: 0 auto;
          background: white;
          font-family: 'Poppins', sans-serif;
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

   async function renderPPTX(blob: Blob) {
     if (!contentContainer || typeof window === 'undefined') return;

    // For PPTX files, we request the preview endpoint which returns a PDF
    try {
      // Request preview endpoint (returns PDF)
      const previewResponse = await apiClient.get(`/documents/${doc.id}/preview?format=pdf`, {
        responseType: 'blob'
      });
      
      // Use existing PDF renderer to display the converted PDF
      await renderPDF(previewResponse.data);
    } catch (err) {
      // If preview fails, show error message
      const errorMsg = err instanceof Error ? err.message : 'Failed to load PPTX preview';
      
       // Check if it's a service unavailable error
       if (errorMsg.includes('LibreOffice') || errorMsg.includes('not available') || errorMsg.includes('503')) {
         contentContainer.innerHTML = `
          <div class="flex items-center justify-center h-full min-h-[400px]">
            <div class="text-center text-gray-600 max-w-md">
              <svg class="w-16 h-16 mx-auto mb-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
              </svg>
              <p class="font-medium text-lg mb-2">PPTX Preview Unavailable</p>
              <p class="text-sm">LibreOffice is required to preview PowerPoint files. Please install LibreOffice to enable this feature.</p>
            </div>
          </div>
        `;
      } else {
        throw new Error(`Failed to render PPTX: ${errorMsg}`);
      }
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
        let html = '<div class="excel-viewer" style="padding: 40px; max-width: 100%; margin: 0 auto; background: white; font-family: \'Poppins\', sans-serif;">';
        
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
            let rowCells: string[] = [];
            
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
              html += `<td style="${cellStyle}"${mergeAttrs}>${escapeHtml(cellValue)}</td>`;
            }
            
            html += '</tr>';
          }
          
          html += '</table>';
          html += '</div>';
        });
        
         html += '</div>';
         
         contentContainer.innerHTML = html;
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
      
      const sides = ['top', 'right', 'bottom', 'left'] as const;
      const borderProps = ['top', 'right', 'bottom', 'left'] as const;
      
      borderProps.forEach((side, index) => {
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
  </script>
  
  <div class="document-viewer-content h-full overflow-y-auto bg-gray-50 relative" bind:this={container}>
    <!-- Loading overlay - shown when isLoading is true -->
    {#if isLoading}
      <div class="flex items-center justify-center h-full min-h-[400px] absolute inset-0 z-20 bg-gray-50">
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
    {#if error}
      <div class="flex items-center justify-center h-full min-h-[400px]">
        <div class="text-center text-red-600">
          <svg class="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
          </svg>
          <p class="font-medium">Error loading document</p>
          <p class="text-sm mt-2">{error}</p>
        </div>
      </div>
    {:else}
      <!-- Content container - always rendered so render functions can use it -->
      <div bind:this={contentContainer} class="h-full w-full"></div>
    {/if}
  </div>
  
   <style>
     :global(.pdf-viewer-container) {
       padding: 20px;
       background: #f5f5f5;
       display: flex;
       flex-direction: column;
       align-items: center;
     }
 
     :global(.pdf-page) {
       background: white;
       margin: 0 auto;
       display: block;
       max-width: 100%;
     }
 
     :global(.pdf-page canvas) {
       display: block;
       max-width: 100%;
       height: auto;
     }
  
    :global(.excel-viewer) {
      padding: 40px;
      max-width: 100%;
      margin: 0 auto;
      background: white;
      font-family: 'Poppins', sans-serif;
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
  </style>
  
  