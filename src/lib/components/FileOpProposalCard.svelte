<script lang="ts">
  import { apiService } from '$lib/api/services';
  import type { FileOpProposal } from '$lib/api/types';

  let {
    proposal,
    onConfirmed = () => {},
    onDiscarded = () => {},
  } = $props<{
    proposal: FileOpProposal;
    onConfirmed?: (id: string) => void;
    onDiscarded?: (id: string) => void;
  }>();

  let state = $state<'idle' | 'confirming' | 'confirmed' | 'discarded' | 'error'>('idle');
  let errorMessage = $state('');

  async function handleConfirm() {
    state = 'confirming';
    try {
      if (proposal.type === 'rename') {
        const result = await apiService.renameFile(proposal.file_path, proposal.new_name!);
        window.dispatchEvent(new CustomEvent('fileModified', {
          detail: { oldPath: proposal.file_path, newPath: result.new_path ?? '' }
        }));
      } else if (proposal.type === 'delete') {
        await apiService.deleteFile(proposal.file_path);
        window.dispatchEvent(new CustomEvent('fileDeleted', {
          detail: { filePath: proposal.file_path }
        }));
      } else if (proposal.type === 'move') {
        const result = await apiService.moveFile(proposal.file_path, proposal.destination_path ?? proposal.destination_folder!);
        window.dispatchEvent(new CustomEvent('fileModified', {
          detail: { oldPath: proposal.file_path, newPath: result.new_path ?? '' }
        }));
      }
      state = 'confirmed';
      onConfirmed(proposal.id);
    } catch (err: any) {
      state = 'error';
      errorMessage = err?.response?.data?.detail ?? err?.message ?? 'Operation failed';
    }
  }

  function handleDiscard() {
    state = 'discarded';
    onDiscarded(proposal.id);
  }

  const isDelete = proposal.type === 'delete';

  function getTitle(): string {
    if (proposal.type === 'rename') return `Rename "${proposal.document_name}"`;
    if (proposal.type === 'delete') return `Delete "${proposal.document_name}"`;
    return `Move "${proposal.document_name}"`;
  }

  function getDetail(): string {
    if (proposal.type === 'rename') return `→ "${proposal.new_name}"`;
    if (proposal.type === 'delete') return 'This file will be permanently deleted and cannot be recovered.';
    return `→ "${proposal.destination_folder}"`;
  }

  function getConfirmLabel(): string {
    if (proposal.type === 'rename') return 'Rename';
    if (proposal.type === 'delete') return 'Delete permanently';
    return 'Move';
  }
</script>

<div class="mt-3 rounded-xl border {isDelete ? 'border-red-200 dark:border-red-900/50' : 'border-[#443C68]/20 dark:border-[#443C68]/40'} bg-white dark:bg-gray-900 shadow-sm overflow-hidden">
  <!-- Header -->
  <div class="flex items-center gap-3 px-4 py-3 {isDelete ? 'bg-red-50 dark:bg-red-950/20 border-b border-red-100 dark:border-red-900/30' : 'bg-[#443C68]/5 dark:bg-[#443C68]/15 border-b border-[#443C68]/10 dark:border-[#443C68]/25'}">
    <div class="w-8 h-8 {isDelete ? 'bg-red-100 dark:bg-red-900/30' : 'bg-[#443C68]/10 dark:bg-[#443C68]/20'} rounded-lg flex items-center justify-center flex-shrink-0">
      {#if proposal.type === 'rename'}
        <svg class="w-4 h-4 text-[#443C68] dark:text-[#C9C2EB]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
        </svg>
      {:else if proposal.type === 'delete'}
        <svg class="w-4 h-4 text-red-500 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      {:else}
        <svg class="w-4 h-4 text-[#443C68] dark:text-[#C9C2EB]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
      {/if}
    </div>
    <div class="flex-1 min-w-0">
      <p class="text-sm font-semibold {isDelete ? 'text-red-700 dark:text-red-300' : 'text-[#37352F] dark:text-gray-100'}">{getTitle()}</p>
      <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">{getDetail()}</p>
    </div>
    {#if state === 'confirmed'}
      <span class="flex-shrink-0 text-xs font-medium text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-900/30 px-2 py-0.5 rounded-full">Done</span>
    {:else if state === 'discarded'}
      <span class="flex-shrink-0 text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">Cancelled</span>
    {:else if state === 'error'}
      <span class="flex-shrink-0 text-xs font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-2 py-0.5 rounded-full">Error</span>
    {:else}
      <span class="flex-shrink-0 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 rounded-full">Pending</span>
    {/if}
  </div>

  {#if state === 'error' && errorMessage}
    <div class="px-4 py-2 bg-red-50 dark:bg-red-950/20 border-b border-red-100 dark:border-red-900/30 text-xs text-red-700 dark:text-red-400">
      {errorMessage}
    </div>
  {/if}

  {#if state === 'idle' || state === 'confirming'}
    <div class="flex items-center gap-2 px-4 py-3 bg-gray-50/50 dark:bg-gray-900/50">
      <button
        type="button"
        onclick={handleConfirm}
        disabled={state === 'confirming'}
        class="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 {isDelete ? 'bg-red-600 hover:bg-red-700' : 'bg-[#443C68] hover:bg-[#3A3457]'} disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg transition-colors"
      >
        {#if state === 'confirming'}
          <svg class="animate-spin w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          Processing…
        {:else}
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          {getConfirmLabel()}
        {/if}
      </button>
      <button
        type="button"
        onclick={handleDiscard}
        disabled={state === 'confirming'}
        class="flex items-center gap-1.5 px-4 py-2 border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 disabled:opacity-60 disabled:cursor-not-allowed text-gray-600 dark:text-gray-300 text-xs font-medium rounded-lg transition-colors bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
        Cancel
      </button>
    </div>
  {/if}
</div>
