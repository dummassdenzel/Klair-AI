<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { open } from '@tauri-apps/plugin-dialog';

  export let isSetting = false;
  /** When true, show a cancel/back button (e.g. when changing folder from chat). */
  export let allowCancel = false;

  const dispatch = createEventDispatcher();

  let selectedDirectory = '';
  let directoryName = '';
  let error: string | null = null;
  let isSelecting = false;
  let cancelled = false;

  async function handleSelectDirectory() {
    if (isSetting || isSelecting) return;

    isSelecting = true;
    cancelled = false;
    error = null;

    try {
      const selected = await open({
        directory: true,
        multiple: false,
        title: 'Select Documents Directory',
      });

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

      isSelecting = false;
    } catch (err: unknown) {
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
  }
</script>

<div class="flex flex-col items-center justify-center min-h-full p-8 bg-white dark:bg-gray-950">
  <div class="w-full max-w-2xl mx-auto">
    <!-- Welcome message with optional logo -->
    <div class="text-center mb-12">
      <img
        src="/klair.ai-sm.png"
        alt="Klair AI"
        class="w-20 h-20 mx-auto mb-4 object-contain"
      />
      <h1 class="text-7xl font-bold tracking-tight text-[#37352F] dark:text-gray-100 mb-2">
        Welcome to Klair AI
      </h1>
      <p class="text-gray-600 dark:text-gray-400 text-sm max-w-md mx-auto">
        Your AI-powered document workspace. 
      </p>
    </div>

    <div class="space-y-6">
      <div class="text-center py-6">
        {#if !selectedDirectory}
          <div class="mb-6">
            
            <p class="text-gray-600 dark:text-gray-400 text-sm mb-4">
              Let's start by choosing the folder containing your documents.
            </p>
            <div class="flex flex-col sm:flex-row items-center justify-center gap-3">
              <button
                type="button"
                onclick={handleSelectDirectory}
                disabled={isSetting || isSelecting}
                class="px-8 py-4 bg-[#443C68] text-white rounded-lg hover:bg-[#3A3457] disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors flex items-center gap-3 text-lg shadow-lg hover:shadow-xl"
              >
                {#if isSelecting}
                  <div
                    class="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin"
                  ></div>
                  Opening File Explorer...
                {:else}
                  <svg
                    class="w-6 h-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
                    />
                  </svg>
                  Choose a Folder
                {/if}
              </button>
              {#if allowCancel}
                <button
                  type="button"
                  onclick={handleCancel}
                  disabled={isSetting || isSelecting}
                  class="px-6 py-3 text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-900 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
                >
                  Back
                </button>
              {/if}
            </div>
          </div>
        {:else}
          <div class="mb-6">
            <div
              class="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4"
            >
              <svg
                class="w-10 h-10 text-green-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </div>
            <h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-2">
              Directory Selected
            </h3>
            <p class="text-gray-700 dark:text-gray-200 font-medium mb-1">{directoryName}</p>
          </div>
        {/if}
      </div>

      {#if error}
        <div
          class="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm"
        >
          {error}
        </div>
      {/if}

      {#if isSetting}
        <div class="text-center py-4">
          <div class="inline-flex items-center gap-3 text-blue-600">
            <div
              class="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"
            ></div>
            <span class="text-sm font-medium">Setting directory…</span>
          </div>
        </div>
      {/if}
    </div>
  </div>
</div>
