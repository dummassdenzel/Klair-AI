<script lang="ts">
  import type { FolderNode } from '$lib/api/types';
  import { apiService } from '$lib/api/services';

  let {
    excludePath = '',
    onConfirm,
    onCancel,
  } = $props<{
    excludePath?: string;
    onConfirm: (folderPath: string) => void;
    onCancel: () => void;
  }>();

  let tree = $state<FolderNode | null>(null);
  let loading = $state(true);
  let error = $state('');
  let selectedPath = $state('');
  let expandedPaths = $state(new Set<string>());

  $effect(() => {
    apiService.getFolders().then(res => {
      tree = res.tree;
      selectedPath = res.root;
      // Expand root by default
      expandedPaths = new Set([res.root]);
      loading = false;
    }).catch(() => {
      error = 'Failed to load folders';
      loading = false;
    });
  });

  function toggle(path: string) {
    const next = new Set(expandedPaths);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    expandedPaths = next;
  }

  // Normalise paths for comparison (strip trailing sep, lowercase on Windows)
  function normPath(p: string) {
    return p.replace(/[\\/]+$/, '').toLowerCase();
  }

  const excludeNorm = $derived(normPath(excludePath));
</script>

<!-- Backdrop -->
<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
  role="dialog"
  aria-modal="true"
>
  <div class="bg-white dark:bg-gray-900 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 w-[420px] max-h-[70vh] flex flex-col overflow-hidden">
    <!-- Header -->
    <div class="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
      <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">Move to…</h2>
      <button onclick={onCancel} class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>

    <!-- Tree -->
    <div class="flex-1 overflow-y-auto px-3 py-3">
      {#if loading}
        <div class="flex items-center justify-center py-8 text-gray-400 text-sm">Loading folders…</div>
      {:else if error}
        <div class="text-red-500 text-sm px-2">{error}</div>
      {:else if tree}
        {@render folderNode(tree, 0)}
      {/if}
    </div>

    <!-- Footer -->
    <div class="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-200 dark:border-gray-700 flex-shrink-0">
      <button
        onclick={onCancel}
        class="px-4 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
      >
        Cancel
      </button>
      <button
        onclick={() => selectedPath && onConfirm(selectedPath)}
        disabled={!selectedPath}
        class="px-4 py-1.5 text-sm rounded-lg bg-[#443C68] text-white hover:bg-[#3A3457] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        Move here
      </button>
    </div>
  </div>
</div>

{#snippet folderNode(node: FolderNode, depth: number)}
  {@const isExcluded = normPath(node.path) === excludeNorm}
  {@const isSelected = normPath(node.path) === normPath(selectedPath)}
  {@const isExpanded = expandedPaths.has(node.path)}
  {@const hasChildren = node.children.length > 0}

  <div>
    <button
      type="button"
      disabled={isExcluded}
      onclick={() => { if (!isExcluded) { selectedPath = node.path; if (hasChildren) toggle(node.path); } }}
      class="w-full text-left flex items-center gap-1.5 py-1.5 px-2 rounded-md text-sm transition-colors
        {isSelected ? 'bg-[#443C68]/10 dark:bg-[#443C68]/25 text-[#443C68] dark:text-[#C9C2EB] font-medium' : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'}
        {isExcluded ? 'opacity-40 cursor-not-allowed' : ''}"
      style="padding-left: {8 + depth * 16}px;"
    >
      <!-- Expand arrow -->
      {#if hasChildren}
        <span class="flex-shrink-0 w-3.5 h-3.5 flex items-center justify-center transition-transform {isExpanded ? 'rotate-90' : ''}">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
          </svg>
        </span>
      {:else}
        <span class="flex-shrink-0 w-3.5 h-3.5"></span>
      {/if}
      <!-- Folder icon -->
      <svg class="w-4 h-4 flex-shrink-0 {isSelected ? 'text-[#443C68] dark:text-[#C9C2EB]' : 'text-[#443C68]/60 dark:text-[#C9C2EB]/60'}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
      </svg>
      <span class="truncate">{node.name}</span>
    </button>

    {#if isExpanded && hasChildren}
      {#each node.children as child}
        {@render folderNode(child, depth + 1)}
      {/each}
    {/if}
  </div>
{/snippet}
