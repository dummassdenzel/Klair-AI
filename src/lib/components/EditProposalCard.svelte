<script lang="ts">
  import { apiService } from '$lib/api/services';
  import FileTypeIcon from '$lib/components/FileTypeIcon.svelte';
  import type { EditProposal } from '$lib/api/types';

  let {
    proposal,
    onApplied = () => {},
    onDiscarded = () => {},
  } = $props<{
    proposal: EditProposal;
    onApplied?: (proposalId: string) => void;
    onDiscarded?: (proposalId: string) => void;
  }>();

  let state = $state<'idle' | 'applying' | 'discarding' | 'applied' | 'discarded' | 'error'>('idle');
  let errorMessage = $state('');
  let expandedIndex = $state<number | null>(null);

  async function handleApply() {
    state = 'applying';
    try {
      await apiService.applyEditProposal(proposal.proposal_id);
      state = 'applied';
      window.dispatchEvent(new CustomEvent('editApplied'));
      onApplied(proposal.proposal_id);
    } catch (err: any) {
      state = 'error';
      errorMessage = err?.response?.data?.detail ?? err?.message ?? 'Failed to apply edit';
    }
  }

  async function handleDiscard() {
    state = 'discarding';
    try {
      await apiService.discardEditProposal(proposal.proposal_id);
      state = 'discarded';
      onDiscarded(proposal.proposal_id);
    } catch {
      state = 'discarded'; // discard is best-effort
      onDiscarded(proposal.proposal_id);
    }
  }

  function toggleChange(i: number) {
    expandedIndex = expandedIndex === i ? null : i;
  }

  const fileLabel = proposal.file_type?.toUpperCase() ?? 'FILE';
</script>

<div class="mt-3 rounded-xl border border-[#443C68]/20 dark:border-[#443C68]/40 bg-white dark:bg-gray-900 shadow-sm overflow-hidden">
  <!-- Header -->
  <div class="flex items-center gap-3 px-4 py-3 bg-[#443C68]/5 dark:bg-[#443C68]/15 border-b border-[#443C68]/10 dark:border-[#443C68]/25">
    <div class="w-8 h-8 bg-[#443C68]/10 dark:bg-[#443C68]/20 rounded-lg flex items-center justify-center flex-shrink-0">
      <FileTypeIcon fileType={proposal.file_type} class="w-4 h-4 flex-shrink-0" />
    </div>
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold text-[#443C68] dark:text-[#C9C2EB] uppercase tracking-wide">{fileLabel}</span>
        <span class="text-sm font-semibold text-[#37352F] dark:text-gray-100 truncate">{proposal.document_name}</span>
      </div>
      <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{proposal.summary}</p>
    </div>
    <!-- Status badge -->
    {#if state === 'applied'}
      <span class="flex-shrink-0 text-xs font-medium text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-900/30 px-2 py-0.5 rounded-full">Applied</span>
    {:else if state === 'discarded'}
      <span class="flex-shrink-0 text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">Discarded</span>
    {:else if state === 'error'}
      <span class="flex-shrink-0 text-xs font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-2 py-0.5 rounded-full">Error</span>
    {:else}
      <span class="flex-shrink-0 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 rounded-full">Pending review</span>
    {/if}
  </div>

  <!-- Changes list -->
  {#if proposal.changes.length > 0}
    <div class="divide-y divide-gray-100 dark:divide-gray-800">
      {#each proposal.changes as change, i}
        {@const isExpanded = expandedIndex === i}
        <div class="px-4 py-2">
          <!-- Change row header -->
          <button
            type="button"
            class="w-full flex items-center justify-between text-left gap-2 group"
            onclick={() => toggleChange(i)}
            disabled={state === 'applied' || state === 'discarded'}
          >
            <span class="text-xs text-gray-500 dark:text-gray-400 font-medium">Change {i + 1}</span>
            <svg
              class="w-3.5 h-3.5 text-gray-400 transition-transform flex-shrink-0 {isExpanded ? 'rotate-180' : ''}"
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          <!-- Expanded diff -->
          {#if isExpanded}
            <div class="mt-2 space-y-1.5">
              <div>
                <span class="text-[10px] font-semibold text-red-500 uppercase tracking-wide">Before</span>
                <div class="mt-1 px-3 py-2 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-lg text-xs text-red-800 dark:text-red-300 font-mono whitespace-pre-wrap break-words leading-relaxed">
                  {change.find}
                </div>
              </div>
              <div class="flex justify-center">
                <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                </svg>
              </div>
              <div>
                <span class="text-[10px] font-semibold text-green-600 uppercase tracking-wide">After</span>
                <div class="mt-1 px-3 py-2 bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-900/50 rounded-lg text-xs text-green-800 dark:text-green-300 font-mono whitespace-pre-wrap break-words leading-relaxed">
                  {change.replace}
                </div>
              </div>
            </div>
          {:else}
            <!-- Collapsed preview -->
            <div class="mt-1.5 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 truncate">
              <span class="font-mono text-red-500 truncate max-w-[40%]">{change.find.slice(0, 50)}{change.find.length > 50 ? '…' : ''}</span>
              <svg class="w-3 h-3 flex-shrink-0 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
              <span class="font-mono text-green-600 dark:text-green-400 truncate max-w-[40%]">{change.replace.slice(0, 50)}{change.replace.length > 50 ? '…' : ''}</span>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  <!-- Error message -->
  {#if state === 'error' && errorMessage}
    <div class="px-4 py-2 bg-red-50 dark:bg-red-950/20 border-t border-red-100 dark:border-red-900/30 text-xs text-red-700 dark:text-red-400">
      {errorMessage}
    </div>
  {/if}

  <!-- Action buttons -->
  {#if state === 'idle' || state === 'applying' || state === 'discarding'}
    <div class="flex items-center gap-2 px-4 py-3 border-t border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-900/50">
      <button
        type="button"
        onclick={handleApply}
        disabled={state !== 'idle'}
        class="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 bg-[#443C68] hover:bg-[#3A3457] disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg transition-colors"
      >
        {#if state === 'applying'}
          <svg class="animate-spin w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          Applying…
        {:else}
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          Apply
        {/if}
      </button>
      <button
        type="button"
        onclick={handleDiscard}
        disabled={state !== 'idle'}
        class="flex items-center gap-1.5 px-4 py-2 border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 disabled:opacity-60 disabled:cursor-not-allowed text-gray-600 dark:text-gray-300 text-xs font-medium rounded-lg transition-colors bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
        Discard
      </button>
    </div>
  {/if}
</div>
