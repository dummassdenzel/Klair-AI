<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { apiService } from '$lib/api/services';

  export let isOpen = false;
  export let isSetting = false;
  export let allowCancel = false; // Allow closing the modal without selecting a directory

  const dispatch = createEventDispatcher();
  
  let directoryInput: HTMLInputElement;
  let selectedDirectory = '';
  let selectedFilesCount = 0;
  let directoryName = '';
  let error: string | null = null;
  let isSelecting = false;
  let previousOpenState = false;
  let cancelled = false; // Track if user cancelled during selection
  
  // Reset state when modal opens (but not during selection)
  $: {
    // Reset only when transitioning from closed to open (not if already open)
    if (isOpen && !previousOpenState && !isSetting && !isSelecting) {
      selectedDirectory = '';
      selectedFilesCount = 0;
      directoryName = '';
      error = null;
      cancelled = false; // Reset cancelled flag when modal opens
    }
    previousOpenState = isOpen;
  }

  async function handleSelectDirectory() {
    if (isSetting || isSelecting) return;
    
    isSelecting = true;
    cancelled = false;
    error = null;
    
    // Try backend directory picker first (opens native file explorer)
    try {
      const response = await apiService.selectDirectory();
      
      // Check if cancelled during the async operation
      if (cancelled) {
        isSelecting = false;
        return;
      }
      
      if (response.status === 'success' && response.directory_path) {
        selectedDirectory = response.directory_path;
        directoryName = selectedDirectory.split(/[/\\]/).pop() || selectedDirectory;
        selectedFilesCount = response.file_count || 0; // Use actual file count from backend
        
        // Auto-submit immediately (only if not cancelled)
        if (!cancelled) {
          setTimeout(() => {
            if (!cancelled) {
              dispatch('select', { directoryPath: selectedDirectory });
            }
            isSelecting = false;
          }, 100);
        } else {
          isSelecting = false;
        }
        return;
      }
    } catch (err: any) {
      // If cancelled, don't log error or fallback
      if (cancelled) {
        isSelecting = false;
        return;
      }
      
      // Backend picker not available or user cancelled - don't fallback automatically
      // Only fallback if it's a real error (not user cancellation)
      if (err?.response?.status !== 400) {
        console.log('Backend directory picker error:', err);
      }
      
      isSelecting = false;
    }
    
    isSelecting = false;
  }

  function handleDirectoryChange(event: Event) {
    const target = event.target as HTMLInputElement;
    const files = target.files;
    
    if (files && files.length > 0) {
      selectedFilesCount = files.length;
      
      // Extract directory name from webkitRelativePath
      const firstFile = files[0];
      if (firstFile.webkitRelativePath) {
        const pathParts = firstFile.webkitRelativePath.split('/');
        pathParts.pop(); // Remove filename
        directoryName = pathParts[0] || 'Selected Directory';
      } else {
        directoryName = 'Selected Directory';
      }
      
      // Try to get path from file object (limited browser support)
      const filePath = (firstFile as any).path || '';
      
      if (filePath) {
        // Extract directory path from file path
        const pathParts = filePath.split(/[/\\]/);
        pathParts.pop(); // Remove filename
        selectedDirectory = pathParts.join('/') || pathParts.join('\\');
        
        // Auto-submit when we have a full path
        setTimeout(() => {
          dispatch('select', { directoryPath: selectedDirectory });
        }, 300);
      } else {
        // Browser picker fallback - can't get full path in modern browsers
        // Set directory name, user can still click Start button
        // Backend will need to handle directory name lookup or we show a message
        selectedDirectory = directoryName;
      }
      
      error = null;
    } else {
      selectedFilesCount = 0;
      directoryName = '';
      selectedDirectory = '';
    }
  }

  function handleManualSubmit() {
    if (!selectedDirectory || isSetting) return;
    dispatch('select', { directoryPath: selectedDirectory });
  }

  function handleCancel(event?: Event) {
    if (!allowCancel || isSetting) return;
    
    // Prevent any event propagation
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    
    // Mark as cancelled (even if selection is in progress)
    cancelled = true;
    
    // Reset state before closing
    selectedDirectory = '';
    selectedFilesCount = 0;
    directoryName = '';
    error = null;
    isSelecting = false;
    
    // Dispatch cancel event and close modal
    dispatch('cancel');
    isOpen = false;
  }
</script>

{#if isOpen}
  <!-- Modal Overlay (can be closed if allowCancel is true) -->
  <div 
    class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 {allowCancel ? 'cursor-pointer' : ''}"
    on:click={allowCancel ? (e) => handleCancel(e) : undefined}
    on:keydown={allowCancel ? (e) => e.key === 'Escape' && handleCancel(e) : undefined}
    role="dialog"
    aria-modal="true"
    aria-labelledby="directory-modal-title"
    tabindex="-1"
  >
    <!-- Modal Content -->
    <!-- svelte-ignore a11y-click-events-have-key-events -->
    <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
    <div 
      class="bg-white rounded-xl shadow-2xl max-w-2xl w-full mx-4 p-8 relative"
      role="document"
      on:click|stopPropagation
    >
      <!-- Cancel button (only shown when allowCancel is true) -->
      {#if allowCancel}
        <button
          type="button"
          on:click|stopPropagation={(e) => handleCancel(e)}
          disabled={isSetting || isSelecting}
          class="absolute top-4 right-4 text-gray-400 hover:text-gray-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          aria-label="Cancel directory selection"
        >
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      {/if}
      <!-- Header -->
      <div class="mb-6">
        <h2 id="directory-modal-title" class="text-2xl font-bold text-gray-900 mb-2">
          Select Document Directory
        </h2>
        <p class="text-gray-600">
          Choose the directory containing your documents (.pdf, .docx, .txt files) to begin.
          This is required before using the RAG system.
        </p>
      </div>

      <!-- Directory Selection -->
      <div class="space-y-6">
        <!-- File Picker (Hidden) -->
        <input
          bind:this={directoryInput}
          type="file"
          webkitdirectory
          multiple
          class="hidden"
          on:change={handleDirectoryChange}
          accept=".pdf,.docx,.txt"
        />

        <!-- Selection Area -->
        <div class="text-center py-8">
          {#if selectedFilesCount === 0}
            <!-- No directory selected -->
            <div class="mb-6">
              <div class="w-20 h-20 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg class="w-10 h-10 text-[#443C68]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
              </div>
              <h3 class="text-lg font-semibold text-gray-900 mb-2">Select Your Documents Directory</h3>
              <p class="text-gray-600 text-sm mb-6">
                Choose the folder containing your PDF, DOCX, or TXT files
              </p>
              <button
                type="button"
                on:click={handleSelectDirectory}
                disabled={isSetting || isSelecting}
                class="px-8 py-4 bg-[#443C68] text-white rounded-lg hover:bg-[#3A3457] disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors flex items-center gap-3 mx-auto text-lg shadow-lg hover:shadow-xl"
              >
                {#if isSelecting}
                  <div class="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  Opening File Explorer...
                {:else}
                  <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                  </svg>
                  Browse Directory
                {/if}
              </button>
            </div>
          {:else}
            <!-- Directory selected - brief confirmation before auto-submit -->
            <div class="mb-6">
              <div class="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg class="w-10 h-10 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 class="text-lg font-semibold text-gray-900 mb-2">Directory Selected</h3>
              <p class="text-gray-700 font-medium mb-1">{directoryName}</p>
              <p class="text-sm text-green-600 mb-6 flex items-center justify-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                {selectedFilesCount} file(s) found
              </p>
              <p class="text-sm text-gray-500 mb-4">Setting directory...</p>
            </div>
          {/if}
        </div>

        <!-- Error Message -->
        {#if error}
          <div class="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        {/if}

        {#if isSetting}
          <div class="text-center py-4">
            <div class="inline-flex items-center gap-3 text-blue-600">
              <div class="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
              <span class="text-sm font-medium">Initializing directory and indexing documents...</span>
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}

