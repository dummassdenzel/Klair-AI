<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { open } from '@tauri-apps/plugin-dialog';

  export let isOpen = false;
  export let isSetting = false;
  export let allowCancel = false;

  const dispatch = createEventDispatcher();
  
  let selectedDirectory = '';
  let directoryName = '';
  let error: string | null = null;
  let isSelecting = false;
  let previousOpenState = false;
  let cancelled = false;
  
  $: {
    if (isOpen && !previousOpenState && !isSetting && !isSelecting) {
      selectedDirectory = '';
      directoryName = '';
      error = null;
      cancelled = false;
    }
    previousOpenState = isOpen;
  }

  async function handleSelectDirectory() {
    if (isSetting || isSelecting) return;
    
    isSelecting = true;
    cancelled = false;
    error = null;
    
    try {
      const selected = await open({ directory: true, multiple: false, title: 'Select Documents Directory' });

      if (cancelled) {
        isSelecting = false;
        return;
      }

      if (selected && typeof selected === 'string') {
        selectedDirectory = selected;
        directoryName = selected.split(/[/\\]/).pop() || selected;

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
      
      // User cancelled the native dialog
      isSelecting = false;
    } catch (err: any) {
      if (cancelled) {
        isSelecting = false;
        return;
      }
      console.error('Directory picker error:', err);
      error = 'Failed to open directory picker. Please try again.';
      isSelecting = false;
    }
  }

  function handleCancel(event?: Event) {
    if (!allowCancel || isSetting) return;
    
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    
    cancelled = true;
    selectedDirectory = '';
    directoryName = '';
    error = null;
    isSelecting = false;
    
    dispatch('cancel');
    isOpen = false;
  }
</script>

{#if isOpen}
  <!-- Modal Overlay -->
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
        <div class="text-center py-8">
          {#if !selectedDirectory}
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
            </div>
          {/if}
        </div>

        {#if error}
          <div class="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        {/if}

        {#if isSetting}
          <div class="text-center py-4">
            <div class="inline-flex items-center gap-3 text-blue-600">
              <div class="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
              <span class="text-sm font-medium">Setting directory…</span>
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}
