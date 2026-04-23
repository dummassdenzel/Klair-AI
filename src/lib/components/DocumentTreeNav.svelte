<script lang="ts">
  import type { IndexedDocument, DocumentTreeNode } from '$lib/api/types';
  import DocumentTreeNav from '$lib/components/DocumentTreeNav.svelte';
  import FileTypeIcon from '$lib/components/FileTypeIcon.svelte';

  let {
    nodes = [],
    expandedPathKeys = new Set<string>(),
    onToggleFolder = () => {},
    onDocumentClick = () => {},
    onFileAction = () => {},
    depth = 0,
  } = $props<{
    nodes: DocumentTreeNode[];
    expandedPathKeys: Set<string>;
    onToggleFolder?: (pathKey: string) => void;
    onDocumentClick?: (doc: IndexedDocument) => void;
    onFileAction?: (action: 'rename' | 'delete' | 'move', doc: IndexedDocument) => void;
    depth?: number;
  }>();

  const paddingLeft = 12;
  const indent = depth * paddingLeft;

  // Track which file's context menu is open (by doc id)
  let openMenuId = $state<number | null>(null);

  function toggleMenu(id: number, e: MouseEvent) {
    e.stopPropagation();
    openMenuId = openMenuId === id ? null : id;
  }

  function doAction(action: 'rename' | 'delete' | 'move', doc: IndexedDocument, e: MouseEvent) {
    e.stopPropagation();
    openMenuId = null;
    onFileAction(action, doc);
  }

  function closeMenu() {
    openMenuId = null;
  }
</script>

<svelte:window onclick={closeMenu} />

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
              onFileAction={onFileAction}
              depth={depth + 1}
            />
          </div>
        {/if}
      </li>
    {:else}
      {@const doc = node.document}
      {@const menuOpen = openMenuId === doc.id}
      <li class="relative">
        <div class="flex items-center group rounded-md hover:bg-gray-200/80 dark:hover:bg-gray-800/80 transition-colors">
          <button
            type="button"
            onclick={() => onDocumentClick(doc)}
            class="flex-1 min-w-0 text-left flex items-center gap-2 py-1.5 pl-2 pr-1 text-sm cursor-pointer"
            title={doc.file_path}
          >
            <FileTypeIcon fileType={doc.file_type} />
            <span class="truncate text-[#37352F] dark:text-gray-100">{node.name}</span>
            {#if doc.chunks_count != null}
              <span class="flex-shrink-0 text-xs text-gray-400 dark:text-gray-500 ml-auto group-hover:hidden">{doc.chunks_count}</span>
            {/if}
          </button>

          <!-- Three-dot menu button (visible on hover or when menu is open) -->
          <button
            type="button"
            onclick={(e) => toggleMenu(doc.id, e)}
            class="flex-shrink-0 flex items-center justify-center w-6 h-6 mr-1 rounded transition-colors text-gray-400 hover:text-gray-600 dark:hover:text-gray-200
              {menuOpen ? 'opacity-100 bg-gray-300/60 dark:bg-gray-700/60' : 'opacity-0 group-hover:opacity-100'}"
            aria-label="File actions"
          >
            <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
              <circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/>
            </svg>
          </button>
        </div>

        <!-- Context menu dropdown -->
        {#if menuOpen}
          <div
            class="absolute right-1 top-full mt-0.5 z-50 w-36 bg-white dark:bg-gray-900 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 text-sm"
            role="menu"
          >
            <button
              type="button"
              onclick={(e) => doAction('rename', doc, e)}
              class="w-full text-left flex items-center gap-2 px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-200 transition-colors"
            >
              <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
              </svg>
              Rename
            </button>
            <button
              type="button"
              onclick={(e) => doAction('move', doc, e)}
              class="w-full text-left flex items-center gap-2 px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-200 transition-colors"
            >
              <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/>
              </svg>
              Move
            </button>
            <div class="border-t border-gray-100 dark:border-gray-800 my-1"></div>
            <button
              type="button"
              onclick={(e) => doAction('delete', doc, e)}
              class="w-full text-left flex items-center gap-2 px-3 py-1.5 hover:bg-red-50 dark:hover:bg-red-950/30 text-red-600 dark:text-red-400 transition-colors"
            >
              <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
              Delete
            </button>
          </div>
        {/if}
      </li>
    {/if}
  {/each}
</ul>
