<script lang="ts">
  import type { IndexedDocument, DocumentTreeNode } from '$lib/api/types';
  import DocumentTreeNav from '$lib/components/DocumentTreeNav.svelte';
  import FileTypeIcon from '$lib/components/FileTypeIcon.svelte';

  let {
    nodes = [],
    expandedPathKeys = new Set<string>(),
    onToggleFolder = () => {},
    onDocumentClick = () => {},
    depth = 0
  } = $props<{
    nodes: DocumentTreeNode[];
    expandedPathKeys: Set<string>;
    onToggleFolder?: (pathKey: string) => void;
    onDocumentClick?: (doc: IndexedDocument) => void;
    depth?: number;
  }>();

  const paddingLeft = 12;
  const indent = depth * paddingLeft;
</script>

<ul class="list-none pl-0" style="padding-left: {indent}px;">
  {#each nodes as node (node.type === 'folder' ? node.pathKey : `file-${node.document.id}`)}
    {#if node.type === 'folder'}
      <li class="select-none">
        <button
          type="button"
          onclick={() => onToggleFolder(node.pathKey)}
          class="w-full text-left flex items-center gap-1 py-1.5 pr-2 rounded-md hover:bg-gray-200/80 dark:hover:bg-gray-800/80 text-gray-700 dark:text-gray-200 text-sm group"
          style="padding-left: {depth > 0 ? 0 : 4}px;"
        >
          <span
            class="flex-shrink-0 w-4 h-4 flex items-center justify-center transition-transform {expandedPathKeys.has(node.pathKey) ? 'rotate-90' : ''}"
            aria-hidden="true"
          >
            <svg class="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
          </span>
          <svg
            class="w-4 h-4 flex-shrink-0 text-[#443C68] dark:text-[#C9C2EB]"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
            />
          </svg>
          <span class="truncate font-medium">{node.name}</span>
        </button>
        {#if expandedPathKeys.has(node.pathKey)}
          <div class="border-l border-gray-200 dark:border-gray-800 ml-2 mt-0.5" style="margin-left: {paddingLeft / 2 + 2}px;">
            <DocumentTreeNav
              nodes={node.children}
              expandedPathKeys={expandedPathKeys}
              onToggleFolder={onToggleFolder}
              onDocumentClick={onDocumentClick}
              depth={depth + 1}
            />
          </div>
        {/if}
      </li>
    {:else}
      <li>
        <button
          type="button"
          onclick={() => onDocumentClick(node.document)}
          class="w-full text-left flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-gray-200/80 dark:hover:bg-gray-800/80 transition-colors cursor-pointer text-sm group"
          title={node.document.file_path}
        >
          <FileTypeIcon fileType={node.document.file_type} />
          <span class="truncate text-[#37352F] dark:text-gray-100">{node.name}</span>
          {#if node.document.chunks_count != null}
            <span class="flex-shrink-0 text-xs text-gray-400 dark:text-gray-500 ml-auto">{node.document.chunks_count}</span>
          {/if}
        </button>
      </li>
    {/if}
  {/each}
</ul>
