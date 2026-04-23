<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount, onDestroy, untrack } from 'svelte';
  import type { ChatSession, IndexedDocument } from '$lib/api/types';
  import { updateQueueStatus, systemStatus } from '$lib/stores/api';
  import DocumentTreeNav from '$lib/components/DocumentTreeNav.svelte';
  import FolderPickerModal from '$lib/components/FolderPickerModal.svelte';
  import type { DocumentTreeNode } from '$lib/api/types';
  import { formatCalendarDate } from '$lib/utils/dateFormat';
  import { apiService } from '$lib/api/services';

  let {
    currentRoute = '/',
    chatHistory = [],
    indexedDocuments = [],
    workspaceRoot = '',
    currentChatSession = null,
    isLoadingDocuments = false,
    isIndexingInProgress = false,
    contentIndexingInProgress = false,
    indexingProgress = { indexed: 0, total: 0 },
    metadataIndexed = false,
    openDropdownId = null,
    onNewChat = () => {},
    onChatClick = () => {},
    onDocumentsClick = () => {},
    onLoadSession = () => {},
    onDeleteSession = () => {},
    onToggleDropdown = () => {},
    onDocumentClick = () => {},
    onRefreshDocuments = () => {},
    collapsed = false,
  } = $props<{
    currentRoute?: string;
    chatHistory?: ChatSession[];
    indexedDocuments?: IndexedDocument[];
    workspaceRoot?: string;
    currentChatSession?: ChatSession | null;
    isLoadingDocuments?: boolean;
    isIndexingInProgress?: boolean;
  contentIndexingInProgress?: boolean;
  indexingProgress?: { indexed: number; total: number };
  metadataIndexed?: boolean;
    openDropdownId?: number | null;
    onNewChat?: () => void;
    onChatClick?: () => void;
    onDocumentsClick?: () => void;
    onLoadSession?: (session: ChatSession) => void;
    onDeleteSession?: (sessionId: number) => void;
    onToggleDropdown?: (sessionId: number, event: MouseEvent) => void;
    onDocumentClick?: (document: IndexedDocument) => void;
    onRefreshDocuments?: () => void;
    collapsed?: boolean;
  }>();

  let sidebarView = $state<'menu' | 'chat' | 'documents'>('menu');
  let isSidebarHovered = $state(false);

  // Save the active view when the document panel opens, restore it when it closes
  let _savedView: 'menu' | 'chat' | 'documents' | null = null;
  $effect(() => {
    if (collapsed) {
      _savedView = untrack(() => sidebarView);
      isSidebarHovered = false;
      sidebarView = 'menu';
    } else if (_savedView !== null) {
      sidebarView = _savedView;
      _savedView = null;
    }
  });

  let isExpanded = $derived(isSidebarHovered || sidebarView !== 'menu');

  // Filtering and sorting state
  let searchQuery = $state('');
  let filterType = $state<string>('all');
  let sortBy = $state<'name' | 'type' | 'size' | 'date' | 'chunks'>('name');
  let sortOrder = $state<'asc' | 'desc'>('asc');
  let showFilterDropdown = $state(false);

  // File operation modals
  type FileOpModal =
    | { type: 'rename'; doc: IndexedDocument; value: string }
    | { type: 'delete'; doc: IndexedDocument }
    | { type: 'move';   doc: IndexedDocument }
    | null;

  let fileOpModal = $state<FileOpModal>(null);
  let fileOpError = $state('');
  let fileOpLoading = $state(false);

  function openFileAction(action: 'rename' | 'delete' | 'move', doc: IndexedDocument) {
    fileOpError = '';
    if (action === 'rename') {
      const name = doc.file_path.replace(/\\/g, '/').split('/').pop() ?? '';
      fileOpModal = { type: 'rename', doc, value: name };
    } else if (action === 'delete') {
      fileOpModal = { type: 'delete', doc };
    } else {
      fileOpModal = { type: 'move', doc };
    }
  }

  async function commitRename() {
    if (fileOpModal?.type !== 'rename') return;
    const { doc, value } = fileOpModal;
    if (!value.trim()) return;
    fileOpLoading = true;
    fileOpError = '';
    try {
      const result = await apiService.renameFile(doc.file_path, value.trim());
      fileOpModal = null;
      window.dispatchEvent(new CustomEvent('fileModified', {
        detail: { oldPath: doc.file_path, newPath: result.new_path ?? '' }
      }));
      onRefreshDocuments();
    } catch (err: any) {
      fileOpError = err?.response?.data?.detail ?? err?.message ?? 'Rename failed';
    } finally {
      fileOpLoading = false;
    }
  }

  async function commitDelete() {
    if (fileOpModal?.type !== 'delete') return;
    const { doc } = fileOpModal;
    fileOpLoading = true;
    fileOpError = '';
    try {
      await apiService.deleteFile(doc.file_path);
      fileOpModal = null;
      window.dispatchEvent(new CustomEvent('fileDeleted', { detail: { filePath: doc.file_path } }));
      onRefreshDocuments();
    } catch (err: any) {
      fileOpError = err?.response?.data?.detail ?? err?.message ?? 'Delete failed';
    } finally {
      fileOpLoading = false;
    }
  }

  async function commitMove(destinationDir: string) {
    if (fileOpModal?.type !== 'move') return;
    const { doc } = fileOpModal;
    fileOpLoading = true;
    fileOpError = '';
    try {
      const result = await apiService.moveFile(doc.file_path, destinationDir);
      fileOpModal = null;
      window.dispatchEvent(new CustomEvent('fileModified', {
        detail: { oldPath: doc.file_path, newPath: result.new_path ?? '' }
      }));
      onRefreshDocuments();
    } catch (err: any) {
      fileOpError = err?.response?.data?.detail ?? err?.message ?? 'Move failed';
      fileOpLoading = false;
    }
  }

  function handleRenameKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') commitRename();
    if (e.key === 'Escape') fileOpModal = null;
  }

  function handleChatClick() {
    sidebarView = 'chat';
    onChatClick();
  }

  function handleDocumentsClick() {
    sidebarView = 'documents';
    onDocumentsClick();
  }

  function openDirectoryPicker() {
    window.dispatchEvent(new CustomEvent('openDirectoryModalFromLayout'));
  }

  let workspaceFolderName = $derived.by(() => {
    const path = $systemStatus?.current_directory ?? workspaceRoot;
    if (!path) return '';
    return path.split('\\').pop() || path.split('/').pop() || path;
  });

  // Get unique file types for filter
  let fileTypes = $derived(Array.from(new Set(indexedDocuments.map((doc: IndexedDocument) => doc.file_type).filter(Boolean))).sort());

  // Filter and sort documents
  let filteredAndSortedDocuments = $derived.by(() => {
    let filtered = indexedDocuments.filter((doc: IndexedDocument) => {
      // Filter by search query
      const fileName = doc.file_path?.split('\\').pop() || doc.file_path?.split('/').pop() || '';
      const matchesSearch = !searchQuery || fileName.toLowerCase().includes(searchQuery.toLowerCase());
      
      // Filter by type
      const matchesType = filterType === 'all' || doc.file_type === filterType;
      
      return matchesSearch && matchesType;
    });

    // Sort documents
    filtered.sort((a: IndexedDocument, b: IndexedDocument) => {
      let comparison = 0;
      
      switch (sortBy) {
        case 'name':
          const nameA = (a.file_path?.split('\\').pop() || a.file_path?.split('/').pop() || '').toLowerCase();
          const nameB = (b.file_path?.split('\\').pop() || b.file_path?.split('/').pop() || '').toLowerCase();
          comparison = nameA.localeCompare(nameB);
          break;
        case 'type':
          comparison = (a.file_type || '').localeCompare(b.file_type || '');
          break;
        case 'size':
          comparison = (a.file_size || 0) - (b.file_size || 0);
          break;
        case 'date':
          const dateA = new Date(a.last_modified || a.indexed_at || 0).getTime();
          const dateB = new Date(b.last_modified || b.indexed_at || 0).getTime();
          comparison = dateA - dateB;
          break;
        case 'chunks':
          comparison = (a.chunks_count || 0) - (b.chunks_count || 0);
          break;
      }
      
      return sortOrder === 'asc' ? comparison : -comparison;
    });

    return filtered;
  });

  /** Build a folder hierarchy from flat document list. Paths are normalized and optionally made relative to workspaceRoot. */
  function buildDocumentTree(docs: IndexedDocument[], root: string): DocumentTreeNode[] {
    const rootNorm = root ? root.replace(/\\/g, '/').replace(/\/+$/, '') + '/' : '';
    const tree = new Map<string, { name: string; pathKey: string; children: DocumentTreeNode[] }>();

    function ensureFolder(segments: string[]): { name: string; pathKey: string; children: DocumentTreeNode[] } {
      if (segments.length === 0) {
        const pathKey = '';
        if (!tree.has(pathKey)) {
          tree.set(pathKey, { name: '', pathKey, children: [] });
        }
        return tree.get(pathKey)!;
      }
      const pathKey = segments.join('/');
      if (tree.has(pathKey)) return tree.get(pathKey)!;
      const name = segments[segments.length - 1];
      const parent = ensureFolder(segments.slice(0, -1));
      const node = { name, pathKey, children: [] as DocumentTreeNode[] };
      parent.children.push({ type: 'folder', name: node.name, pathKey: node.pathKey, children: node.children });
      tree.set(pathKey, node);
      return node;
    }

    for (const doc of docs) {
      const full = (doc.file_path || '').replace(/\\/g, '/');
      const relative = rootNorm && full.startsWith(rootNorm) ? full.slice(rootNorm.length) : full;
      const segments = relative.split('/').filter(Boolean);
      if (segments.length === 0) continue;
      const fileName = segments.pop()!;
      const folder = ensureFolder(segments);
      folder.children.push({ type: 'file', name: fileName, document: doc });
    }

    function sortNodes(nodes: DocumentTreeNode[]): void {
      nodes.sort((a, b) => {
        const aIsFolder = a.type === 'folder';
        const bIsFolder = b.type === 'folder';
        if (aIsFolder !== bIsFolder) return aIsFolder ? -1 : 1;
        const nameA = (a.type === 'folder' ? a.name : a.name).toLowerCase();
        const nameB = (b.type === 'folder' ? b.name : b.name).toLowerCase();
        return nameA.localeCompare(nameB, undefined, { sensitivity: 'base' });
      });
      for (const n of nodes) {
        if (n.type === 'folder') sortNodes(n.children);
      }
    }

    const rootNode = tree.get('');
    const rootChildren = rootNode ? rootNode.children : [];
    sortNodes(rootChildren);
    return rootChildren;
  }

  let documentTreeRoots = $derived(buildDocumentTree(filteredAndSortedDocuments, workspaceRoot));
  let expandedPathKeys = $state<Set<string>>(new Set());

  // Default-expand root-level folders once when tree has data
  $effect(() => {
    const roots = documentTreeRoots;
    if (roots.length === 0 || expandedPathKeys.size > 0) return;
    const next = new Set<string>();
    for (const node of roots) {
      if (node.type === 'folder') next.add(node.pathKey);
    }
    expandedPathKeys = next;
  });

  function toggleFolder(pathKey: string) {
    expandedPathKeys = new Set(expandedPathKeys);
    if (expandedPathKeys.has(pathKey)) {
      expandedPathKeys.delete(pathKey);
    } else {
      expandedPathKeys.add(pathKey);
    }
  }

  // Close dropdown when clicking outside
  function handleClickOutside(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (!target.closest('.filter-dropdown-container')) {
      showFilterDropdown = false;
    }
  }

  onMount(() => {
    window.addEventListener('click', handleClickOutside);
    return () => {
      window.removeEventListener('click', handleClickOutside);
    };
  });
</script>

<!-- Left Sidebar -->
<div 
  class="bg-[#F7F7F7] dark:bg-gray-900 border-r border-gray-100 dark:border-gray-800 flex flex-col overflow-hidden overflow-x-hidden flex-shrink-0 transition-all duration-300 {isExpanded ? 'w-80' : 'w-20'}"
  onmouseenter={() => { isSidebarHovered = true; }}
  onmouseleave={() => {
    if (sidebarView === 'menu') isSidebarHovered = false;
  }}
  role="navigation"
  aria-label="Sidebar navigation"
>
  
  <!-- Logo and Title -->
  <div class="flex justify-center items-center gap-3 pt-10 pb-6 px-4">
    <div class="flex items-center overflow-hidden">
      <img src="/klair.ai-sm.png" class="w-10 h-10 flex-shrink-0" alt="klair.ai logo" />
      <span class="font-bold text-xl text-gray-700 dark:text-gray-100 whitespace-nowrap transition-opacity duration-300 {isExpanded ? 'opacity-100' : 'opacity-0 w-0'}">klair.ai</span>
    </div>
  </div>

  {#if sidebarView === 'menu'}
    <!-- Menu View -->
    <div class="flex-1 overflow-y-auto overflow-x-hidden pb-6 transition-all duration-300 {isExpanded ? 'px-6' : 'px-3'}">
      <div class="space-y-2">
        <!-- Workspace folder (moved from chat top-right) -->
        {#if isExpanded}
          <div class="mb-2">
            <p class="text-[0.65rem] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide px-0.5">
              Workspace
            </p>
            <div
              class="mt-2 rounded-xl bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 pl-3 pr-1 py-1.5 text-xs text-[#37352F] dark:text-gray-100 flex items-center gap-1 min-w-0 shadow-sm"
            >
              <svg class="w-5 h-5 shrink-0 text-[#443C68]" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
              <span class="truncate flex-1 min-w-0 py-1" title={$systemStatus?.current_directory ?? workspaceRoot}>
                {#if $systemStatus?.directory_set}
                  /{workspaceFolderName}
                {:else}
                  No directory set
                {/if}
              </span>
              <button
                type="button"
                onclick={openDirectoryPicker}
                class="shrink-0 p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-[#443C68] dark:hover:text-[#C9C2EB] hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                title={$systemStatus?.directory_set ? 'Change folder' : 'Choose folder'}
                aria-label="Change workspace folder"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>
            <div
              class="my-3 border-t border-gray-200 dark:border-gray-800"
              aria-hidden="true"
            ></div>
          </div>
        {:else}
          <div class="mb-2 flex justify-center">
            <button
              type="button"
              onclick={openDirectoryPicker}
              class="flex h-12 w-12 items-center justify-center rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 text-[#443C68] shadow-sm hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors"
              title={$systemStatus?.directory_set ? `Workspace: ${workspaceFolderName}` : 'Choose workspace folder'}
              aria-label="Change workspace folder"
            >
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
            </button>
          </div>
        {/if}

        <!-- New Chat Button -->
        <button
          onclick={onNewChat}
          class="w-full py-3 {isExpanded ? 'px-6' : 'px-3'} bg-[#443C68] text-white rounded-xl hover:bg-[#3A3457] transition-all duration-300 flex items-center justify-center border border-[#443C68] shadow-sm mb-4 h-[48px]"
          title="New Chat"
        >
          {#if isExpanded}
            <svg class="w-5 h-5 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
            <span class="font-medium whitespace-nowrap">New Chat</span>
          {:else}
            <div class="w-8 h-8 flex items-center justify-center flex-shrink-0">
              <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
              </svg>
            </div>
          {/if}
        </button>

        <!-- Chat Button -->
        <button
          onclick={handleChatClick}
          class="w-full py-3 {isExpanded ? 'px-6' : 'px-3'} bg-white dark:bg-gray-950 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-900 transition-all duration-300 flex items-center {isExpanded ? 'justify-between' : 'justify-center'} border border-gray-200 dark:border-gray-800 hover:border-[#443C68]/30 shadow-sm group h-[48px]"
          title="Chat"
        >
          {#if isExpanded}
            <div class="flex items-center gap-3">
              <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <span class="font-medium text-[#37352F] dark:text-gray-100 whitespace-nowrap">Chat</span>
            </div>
            <svg class="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
          {:else}
            <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
          {/if}
        </button>

        <!-- Indexed Documents Button -->
        <button
          onclick={handleDocumentsClick}
          class="w-full py-3 {isExpanded ? 'px-6' : 'px-3'} bg-white dark:bg-gray-950 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-900 transition-all duration-300 flex items-center {isExpanded ? 'justify-between' : 'justify-center'} border border-gray-200 dark:border-gray-800 hover:border-[#443C68]/30 shadow-sm group h-[48px]"
          title="Indexed Documents"
        >
          {#if isExpanded}
            <div class="flex items-center gap-3">
              <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <span class="font-medium text-[#37352F] dark:text-gray-100 whitespace-nowrap">Documents</span>
              {#if isIndexingInProgress}
                <span class="flex items-center gap-1 bg-blue-100 text-blue-600 text-xs px-2 py-0.5 rounded-full flex-shrink-0">
                  <svg class="animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Indexing Metadata
                </span>
              {:else if contentIndexingInProgress}
                <span class="flex items-center gap-1 bg-amber-100 text-amber-600 text-xs px-2 py-0.5 rounded-full flex-shrink-0">
                  <svg class="animate-spin h-3 w-3 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  {#if indexingProgress.total > 0}
                    {indexingProgress.indexed}/{indexingProgress.total}
                  {:else}
                    Indexing…
                  {/if}
                </span>
              {:else if indexedDocuments.length > 0}
                <span class="bg-[#443C68] text-white text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0">
                  {indexedDocuments.length}
                </span>
              {/if}
            </div>
            <svg class="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
          {:else}
            <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          {/if}
        </button>

        <!-- Settings Button -->
        <button
          onclick={() => goto('/settings')}
          class="w-full py-3 {isExpanded ? 'px-6' : 'px-3'} bg-white dark:bg-gray-950 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-900 transition-all duration-300 flex items-center {isExpanded ? 'justify-between' : 'justify-center'} border border-gray-200 dark:border-gray-800 hover:border-[#443C68]/30 shadow-sm group h-[48px]"
          title="Settings"
        >
          {#if isExpanded}
            <div class="flex items-center gap-3">
              <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.4 15a1.7 1.7 0 00.33 1.87l.02.02a2 2 0 01-1.41 3.41h-.02a1.7 1.7 0 00-1.87.33 1.7 1.7 0 00-.5 1.83v.02A2 2 0 0112 24a2 2 0 01-1.9-1.4v-.02a1.7 1.7 0 00-.5-1.83 1.7 1.7 0 00-1.87-.33h-.02A2 2 0 014.3 18.9l.02-.02A1.7 1.7 0 004.65 15a1.7 1.7 0 00-1.83-.5h-.02A2 2 0 010 12a2 2 0 011.4-1.9h.02a1.7 1.7 0 001.83-.5A1.7 1.7 0 004.65 7.73l-.02-.02A2 2 0 014.3 5.1h.02a1.7 1.7 0 001.87-.33 1.7 1.7 0 00.5-1.83v-.02A2 2 0 0112 0a2 2 0 011.9 1.4v.02a1.7 1.7 0 00.5 1.83 1.7 1.7 0 001.87.33h.02A2 2 0 0119.7 5.1l-.02.02a1.7 1.7 0 00-.33 1.87 1.7 1.7 0 00.5 1.83 1.7 1.7 0 001.83.5h.02A2 2 0 0124 12a2 2 0 01-1.4 1.9h-.02a1.7 1.7 0 00-1.83.5z" />
              </svg>
              <span class="font-medium text-[#37352F] dark:text-gray-100 whitespace-nowrap">Settings</span>
            </div>
            <svg class="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
          {:else}
            <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.4 15a1.7 1.7 0 00.33 1.87l.02.02a2 2 0 01-1.41 3.41h-.02a1.7 1.7 0 00-1.87.33 1.7 1.7 0 00-.5 1.83v.02A2 2 0 0112 24a2 2 0 01-1.9-1.4v-.02a1.7 1.7 0 00-.5-1.83 1.7 1.7 0 00-1.87-.33h-.02A2 2 0 014.3 18.9l.02-.02A1.7 1.7 0 004.65 15a1.7 1.7 0 00-1.83-.5h-.02A2 2 0 010 12a2 2 0 011.4-1.9h.02a1.7 1.7 0 001.83-.5A1.7 1.7 0 004.65 7.73l-.02-.02A2 2 0 014.3 5.1h.02a1.7 1.7 0 001.87-.33 1.7 1.7 0 00.5-1.83v-.02A2 2 0 0112 0a2 2 0 011.9 1.4v.02a1.7 1.7 0 00.5 1.83 1.7 1.7 0 001.87.33h.02A2 2 0 0119.7 5.1l-.02.02a1.7 1.7 0 00-.33 1.87 1.7 1.7 0 00.5 1.83 1.7 1.7 0 001.83.5h.02A2 2 0 0124 12a2 2 0 01-1.4 1.9h-.02a1.7 1.7 0 00-1.83.5z" />
            </svg>
          {/if}
        </button>

      </div>
    </div>
  {:else if sidebarView === 'chat'}
    <!-- Chat History View -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Back Button and Header -->
      <div class="px-6 pt-4 pb-2 border-b border-gray-200 dark:border-gray-800">
        <button
          onclick={() => sidebarView = 'menu'}
          class="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 hover:text-[#443C68] dark:hover:text-white transition-colors mb-4"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </button>
        <h3 class="text-sm font-semibold text-[#37352F] dark:text-gray-100 uppercase tracking-wide">
          Chat History
        </h3>
      </div>

      <!-- New Chat Button -->
      <div class="p-6 border-b border-gray-100 dark:border-gray-800">
        <button
          onclick={onNewChat}
          class="w-full px-6 py-3 bg-[#443C68] text-white rounded-xl hover:bg-[#3A3457] transition-colors flex items-center justify-center gap-3 font-medium"
        >
          <svg
            class="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M12 4v16m8-8H4"
            ></path>
          </svg>
          New Chat
        </button>
      </div>

      <!-- Chat History List -->
      <div class="flex-1 overflow-y-auto p-6">
        <div class="space-y-3">
      {#each chatHistory as session}
        <div
          class="group relative w-full p-4 rounded-xl hover:bg-white dark:hover:bg-gray-950/60 transition-all duration-200 {currentChatSession?.id ===
          session.id
            ? 'bg-white dark:bg-gray-950 shadow-sm border border-[#443C68]/20 dark:border-[#443C68]/40'
            : ''}"
        >
          <button
            onclick={() => {
              onToggleDropdown(-1, new MouseEvent('click'));
              onLoadSession(session);
            }}
            class="w-full text-left"
          >
            <div class="text-sm font-medium text-[#37352F] dark:text-gray-100 truncate mb-2">
              {session.title}
            </div>
            <div
              class="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400"
            >
              <span>{formatCalendarDate(session.created_at)}</span>
              <span
                class="bg-[#443C68]/10 text-[#443C68] dark:text-[#B9B2E6] px-2.5 py-1 rounded-full font-medium"
              >
                {session.message_count} message{session.message_count !== 1
                  ? "s"
                  : ""}
          </span>
            </div>
          </button>
          
          <!-- Triple-dot dropdown button -->
          <div class="absolute top-3 right-3 dropdown-container">
            <button
              type="button"
              onclick={(e) => onToggleDropdown(session.id, e)}
              class="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
              aria-label="Session options"
              aria-expanded={openDropdownId === session.id}
            >
              <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z" />
              </svg>
            </button>
            
            <!-- Dropdown menu -->
            {#if openDropdownId === session.id}
              <div
                class="absolute right-0 mt-1 w-40 bg-white dark:bg-gray-950 rounded-lg shadow-lg border border-gray-200 dark:border-gray-800 py-1 z-50"
                role="menu"
                onclick={(e) => e.stopPropagation()}
                onkeydown={(e) => e.stopPropagation()}
                tabindex="0"
              >
                <button
                  type="button"
                  onclick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(session.id);
                  }}
                  class="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors flex items-center gap-2"
                  role="menuitem"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  Delete
                </button>
              </div>
            {/if}
          </div>
        </div>
      {/each}
        </div>
      </div>
    </div>
  {:else if sidebarView === 'documents'}
    <!-- Indexed Documents View -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Back Button and Header -->
      <div class="px-6 pt-4 pb-2 border-b border-gray-200 dark:border-gray-800">
        <button
          onclick={() => sidebarView = 'menu'}
          class="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 hover:text-[#443C68] dark:hover:text-white transition-colors mb-4"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </button>
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-[#37352F] dark:text-gray-100 uppercase tracking-wide">
            Indexed Documents
          </h3>
          {#if isIndexingInProgress}
            <span class="flex items-center gap-1 bg-blue-100 text-blue-600 text-xs px-2 py-0.5 rounded-full">
              <svg class="animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Indexing...
            </span>
          {:else if indexedDocuments.length > 0}
            <span class="bg-[#443C68] text-white text-xs px-2 py-0.5 rounded-full font-medium">
              {indexedDocuments.length}
            </span>
          {/if}
          <!-- Phase 3: Update Queue Status -->
          {#if $updateQueueStatus && ($updateQueueStatus.pending > 0 || $updateQueueStatus.processing > 0)}
            <span class="flex items-center gap-1 bg-amber-100 text-amber-600 text-xs px-2 py-0.5 rounded-full" title="Updates pending: {$updateQueueStatus.pending}, Processing: {$updateQueueStatus.processing}">
              <svg class="animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Updating
            </span>
          {/if}
        </div>
      </div>

      <!-- Documents List -->
      <div class="flex-1 flex flex-col overflow-hidden">
        <!-- Search and Filter Controls -->
        {#if indexedDocuments.length > 0}
          <div class="px-6 pt-4 pb-3 border-b border-gray-200 dark:border-gray-800">
            <!-- Single line: Search, Filter dropdown, Sort order -->
            <div class="flex items-center gap-2">
              <!-- Search Input -->
              <div class="relative flex-1">
                <input
                  type="text"
                  placeholder="Search"
                  bind:value={searchQuery}
                  class="w-full px-3 py-2 pl-9 text-sm border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#443C68] focus:border-transparent"
                />
                <svg class="absolute left-3 top-2.5 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>

              <!-- Filter Dropdown Button -->
              <div class="relative filter-dropdown-container">
                <button
                  type="button"
                  onclick={(e) => {
                    e.stopPropagation();
                    showFilterDropdown = !showFilterDropdown;
                  }}
                  class="px-3 py-2 border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-950 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-center"
                  title="Filter & Sort"
                  aria-label="Filter and sort options"
                >
                  <svg class="w-4 h-4 text-gray-600 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                  </svg>
                </button>

                <!-- Filter Dropdown Menu -->
                {#if showFilterDropdown}
                  <div
                    class="absolute right-0 mt-1 w-56 bg-white dark:bg-gray-950 rounded-lg shadow-lg border border-gray-200 dark:border-gray-800 py-1 z-50"
                    role="menu"
                    onclick={(e) => e.stopPropagation()}
                    onkeydown={(e) => e.stopPropagation()}
                    tabindex="0"
                  >
                    <!-- Filter by Type Section -->
                    <div class="px-3 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide border-b border-gray-100 dark:border-gray-800">
                      Filter by Type
                    </div>
                    <button
                      type="button"
                      onclick={() => {
                        filterType = 'all';
                        showFilterDropdown = false;
                      }}
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-between {filterType === 'all' ? 'bg-gray-50 dark:bg-gray-900 text-[#443C68] dark:text-white font-medium' : ''}"
                      role="menuitem"
                    >
                      <span>All Types</span>
                      {#if filterType === 'all'}
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                        </svg>
                      {/if}
                    </button>
                    {#each fileTypes as type (type)}
                      <button
                        type="button"
                        onclick={() => {
                          filterType = String(type);
                          showFilterDropdown = false;
                        }}
                        class="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-between {filterType === String(type) ? 'bg-gray-50 dark:bg-gray-900 text-[#443C68] dark:text-white font-medium' : ''}"
                        role="menuitem"
                      >
                        <span>{String(type).toUpperCase()}</span>
                        {#if filterType === String(type)}
                          <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                          </svg>
                        {/if}
                      </button>
                    {/each}

                    <!-- Sort by Section -->
                    <div class="px-3 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide border-t border-gray-100 dark:border-gray-800 mt-1">
                      Sort by
                    </div>
                    <button
                      type="button"
                      onclick={() => {
                        sortBy = 'name';
                        showFilterDropdown = false;
                      }}
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-between {sortBy === 'name' ? 'bg-gray-50 dark:bg-gray-900 text-[#443C68] dark:text-white font-medium' : ''}"
                      role="menuitem"
                    >
                      <span>Name</span>
                      {#if sortBy === 'name'}
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                        </svg>
                      {/if}
                    </button>
                    <button
                      type="button"
                      onclick={() => {
                        sortBy = 'type';
                        showFilterDropdown = false;
                      }}
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-between {sortBy === 'type' ? 'bg-gray-50 dark:bg-gray-900 text-[#443C68] dark:text-white font-medium' : ''}"
                      role="menuitem"
                    >
                      <span>Type</span>
                      {#if sortBy === 'type'}
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                        </svg>
                      {/if}
                    </button>
                    <button
                      type="button"
                      onclick={() => {
                        sortBy = 'size';
                        showFilterDropdown = false;
                      }}
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-between {sortBy === 'size' ? 'bg-gray-50 dark:bg-gray-900 text-[#443C68] dark:text-white font-medium' : ''}"
                      role="menuitem"
                    >
                      <span>Size</span>
                      {#if sortBy === 'size'}
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                        </svg>
                      {/if}
                    </button>
                    <button
                      type="button"
                      onclick={() => {
                        sortBy = 'date';
                        showFilterDropdown = false;
                      }}
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-between {sortBy === 'date' ? 'bg-gray-50 dark:bg-gray-900 text-[#443C68] dark:text-white font-medium' : ''}"
                      role="menuitem"
                    >
                      <span>Date</span>
                      {#if sortBy === 'date'}
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                        </svg>
                      {/if}
                    </button>
                    <button
                      type="button"
                      onclick={() => {
                        sortBy = 'chunks';
                        showFilterDropdown = false;
                      }}
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-between {sortBy === 'chunks' ? 'bg-gray-50 dark:bg-gray-900 text-[#443C68] dark:text-white font-medium' : ''}"
                      role="menuitem"
                    >
                      <span>Chunks</span>
                      {#if sortBy === 'chunks'}
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                        </svg>
                      {/if}
                    </button>
                  </div>
                {/if}
              </div>

              <!-- Sort Order Toggle -->
              <button
                onclick={() => sortOrder = sortOrder === 'asc' ? 'desc' : 'asc'}
                class="px-3 py-2 border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-950 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-center"
                title={sortOrder === 'asc' ? 'Ascending' : 'Descending'}
              >
                {#if sortOrder === 'asc'}
                  <svg class="w-4 h-4 text-gray-600 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12" />
                  </svg>
                {:else}
                  <svg class="w-4 h-4 text-gray-600 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4h13M3 8h9m-9 4h9m5 4v-6m0 0l-4 4m4-4l4 4" />
                  </svg>
                {/if}
              </button>
            </div>
          </div>
        {/if}

        <!-- Documents List -->
        <div class="flex-1 overflow-y-auto p-6">
          {#if isLoadingDocuments}
          <div class="flex items-center justify-center py-8">
            <svg class="animate-spin h-6 w-6 text-[#443C68]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          </div>
        {:else if indexedDocuments.length === 0}
          <div class="text-center py-8 text-gray-500 text-sm">
            No documents indexed yet
          </div>
        {:else if filteredAndSortedDocuments.length === 0}
          <div class="text-center py-8 text-gray-500 text-sm">
            No documents match your filters
          </div>
        {:else}
          <div class="py-2">
            <DocumentTreeNav
              nodes={documentTreeRoots}
              expandedPathKeys={expandedPathKeys}
              onToggleFolder={toggleFolder}
              onDocumentClick={onDocumentClick}
              onFileAction={openFileAction}
            />
          </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</div>

<!-- ── File operation modals ── -->

{#if fileOpModal?.type === 'rename'}
  {@const modal = fileOpModal}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal="true">
    <div class="bg-white dark:bg-gray-900 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 w-[380px] p-5 flex flex-col gap-4">
      <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">Rename file</h2>
      <input
        type="text"
        bind:value={modal.value}
        onkeydown={handleRenameKeydown}
        class="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-[#37352F] dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-[#443C68]/40"
        autofocus
      />
      {#if fileOpError}
        <p class="text-xs text-red-500">{fileOpError}</p>
      {/if}
      <div class="flex justify-end gap-2">
        <button onclick={() => fileOpModal = null} class="px-4 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">Cancel</button>
        <button
          onclick={commitRename}
          disabled={fileOpLoading || !modal.value.trim()}
          class="px-4 py-1.5 text-sm rounded-lg bg-[#443C68] text-white hover:bg-[#3A3457] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {fileOpLoading ? 'Renaming…' : 'Rename'}
        </button>
      </div>
    </div>
  </div>
{/if}

{#if fileOpModal?.type === 'delete'}
  {@const modal = fileOpModal}
  {@const fileName = modal.doc.file_path.replace(/\\/g, '/').split('/').pop() ?? modal.doc.file_path}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal="true">
    <div class="bg-white dark:bg-gray-900 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 w-[380px] p-5 flex flex-col gap-4">
      <div class="flex items-start gap-3">
        <div class="flex-shrink-0 w-9 h-9 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
          <svg class="w-4 h-4 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
          </svg>
        </div>
        <div>
          <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">Delete file</h2>
          <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
            <span class="font-medium text-[#37352F] dark:text-gray-200">{fileName}</span> will be permanently deleted. This cannot be undone.
          </p>
        </div>
      </div>
      {#if fileOpError}
        <p class="text-xs text-red-500">{fileOpError}</p>
      {/if}
      <div class="flex justify-end gap-2">
        <button onclick={() => fileOpModal = null} class="px-4 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">Cancel</button>
        <button
          onclick={commitDelete}
          disabled={fileOpLoading}
          class="px-4 py-1.5 text-sm rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {fileOpLoading ? 'Deleting…' : 'Delete'}
        </button>
      </div>
    </div>
  </div>
{/if}

{#if fileOpModal?.type === 'move'}
  {@const modal = fileOpModal}
  <FolderPickerModal
    excludePath={modal.doc.file_path.replace(/\\/g, '/').split('/').slice(0, -1).join('/')}
    onConfirm={commitMove}
    onCancel={() => fileOpModal = null}
  />
{/if}

