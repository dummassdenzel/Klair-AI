<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount, onDestroy } from 'svelte';
  import type { ChatSession, IndexedDocument } from '$lib/api/types';
  import { updateQueueStatus } from '$lib/stores/api';

  let {
    currentRoute = '/',
    chatHistory = [],
    indexedDocuments = [],
    currentChatSession = null,
    isLoadingDocuments = false,
    isIndexingInProgress = false,
    contentIndexingInProgress = false,
    metadataIndexed = false,
    openDropdownId = null,
    onNewChat = () => {},
    onChatClick = () => {},
    onDocumentsClick = () => {},
    onLoadSession = () => {},
    onDeleteSession = () => {},
    onToggleDropdown = () => {},
    onDocumentClick = () => {}
  } = $props<{
    currentRoute?: string;
    chatHistory?: ChatSession[];
    indexedDocuments?: IndexedDocument[];
    currentChatSession?: ChatSession | null;
    isLoadingDocuments?: boolean;
    isIndexingInProgress?: boolean;
  contentIndexingInProgress?: boolean;
  metadataIndexed?: boolean;
    openDropdownId?: number | null;
    onNewChat?: () => void;
    onChatClick?: () => void;
    onDocumentsClick?: () => void;
    onLoadSession?: (session: ChatSession) => void;
    onDeleteSession?: (sessionId: number) => void;
    onToggleDropdown?: (sessionId: number, event: MouseEvent) => void;
    onDocumentClick?: (document: IndexedDocument) => void;
  }>();

  let sidebarView = $state<'menu' | 'chat' | 'documents'>('menu');
  let isSidebarHovered = $state(false);

  // Filtering and sorting state
  let searchQuery = $state('');
  let filterType = $state<string>('all');
  let sortBy = $state<'name' | 'type' | 'size' | 'date' | 'chunks'>('name');
  let sortOrder = $state<'asc' | 'desc'>('asc');
  let showFilterDropdown = $state(false);

  function handleChatClick() {
    sidebarView = 'chat';
    onChatClick();
  }

  function handleDocumentsClick() {
    sidebarView = 'documents';
    onDocumentsClick();
  }

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
  class="bg-[#F7F7F7] border-r border-gray-100 flex flex-col overflow-hidden overflow-x-hidden flex-shrink-0 transition-all duration-300 {(isSidebarHovered || sidebarView !== 'menu') ? 'w-80' : 'w-20'}"
  onmouseenter={() => isSidebarHovered = true}
  onmouseleave={() => {
    // Only collapse if we're in menu view
    if (sidebarView === 'menu') {
      isSidebarHovered = false;
    }
  }}
  role="navigation"
  aria-label="Sidebar navigation"
>
  
  <!-- Logo and Title -->
  <div class="flex justify-center items-center gap-3 pt-10 pb-6 px-4">
    <div class="flex items-center space-x-2 overflow-hidden">
      <img src="/klair.ai-sm.png" class="w-7 h-7 flex-shrink-0" alt="klair.ai logo" />
      <span class="font-bold text-xl text-gray-700 whitespace-nowrap transition-opacity duration-300 {(isSidebarHovered || sidebarView !== 'menu') ? 'opacity-100' : 'opacity-0 w-0'}">klair.ai</span>
    </div>
  </div>

  {#if sidebarView === 'menu'}
    <!-- Menu View -->
    <div class="flex-1 overflow-y-auto overflow-x-hidden pb-6 transition-all duration-300 {(isSidebarHovered || sidebarView !== 'menu') ? 'px-6' : 'px-3'}">
      <div class="space-y-2">
        <!-- New Chat Button -->
        <button
          onclick={onNewChat}
          class="w-full py-3 {(isSidebarHovered || sidebarView !== 'menu') ? 'px-6' : 'px-3'} bg-[#443C68] text-white rounded-xl hover:bg-[#3A3457] transition-all duration-300 flex items-center justify-center border border-[#443C68] shadow-sm mb-4 h-[48px]"
          title="New Chat"
        >
          {#if (isSidebarHovered || sidebarView !== 'menu')}
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
          class="w-full py-3 {(isSidebarHovered || sidebarView !== 'menu') ? 'px-6' : 'px-3'} bg-white rounded-xl hover:bg-gray-50 transition-all duration-300 flex items-center {(isSidebarHovered || sidebarView !== 'menu') ? 'justify-between' : 'justify-center'} border border-gray-200 hover:border-[#443C68]/30 shadow-sm group h-[48px]"
          title="Chat"
        >
          {#if (isSidebarHovered || sidebarView !== 'menu')}
            <div class="flex items-center gap-3">
              <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <span class="font-medium text-[#37352F] whitespace-nowrap">Chat</span>
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
          class="w-full py-3 {(isSidebarHovered || sidebarView !== 'menu') ? 'px-6' : 'px-3'} bg-white rounded-xl hover:bg-gray-50 transition-all duration-300 flex items-center {(isSidebarHovered || sidebarView !== 'menu') ? 'justify-between' : 'justify-center'} border border-gray-200 hover:border-[#443C68]/30 shadow-sm group h-[48px]"
          title="Indexed Documents"
        >
          {#if (isSidebarHovered || sidebarView !== 'menu')}
            <div class="flex items-center gap-3">
              <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <span class="font-medium text-[#37352F] whitespace-nowrap">Documents</span>
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
                  <svg class="animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Indexing Content
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

        <!-- Metrics Button -->
        <button
          onclick={() => goto('/metrics')}
          class="w-full py-3 {(isSidebarHovered || sidebarView !== 'menu') ? 'px-6' : 'px-3'} bg-white rounded-xl hover:bg-gray-50 transition-all duration-300 flex items-center {(isSidebarHovered || sidebarView !== 'menu') ? 'justify-between' : 'justify-center'} border border-gray-200 hover:border-[#443C68]/30 shadow-sm group h-[48px] {(currentRoute === '/metrics') ? 'bg-[#443C68]/10 border-[#443C68]/30' : ''}"
          title="Metrics"
        >
          {#if (isSidebarHovered || sidebarView !== 'menu')}
            <div class="flex items-center gap-3">
              <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              <span class="font-medium text-[#37352F] whitespace-nowrap">Metrics</span>
            </div>
            <svg class="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
          {:else}
            <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          {/if}
        </button>

        <!-- Analytics Button -->
        <button
          onclick={() => goto('/analytics')}
          class="w-full py-3 {(isSidebarHovered || sidebarView !== 'menu') ? 'px-6' : 'px-3'} bg-white rounded-xl hover:bg-gray-50 transition-all duration-300 flex items-center {(isSidebarHovered || sidebarView !== 'menu') ? 'justify-between' : 'justify-center'} border border-gray-200 hover:border-[#443C68]/30 shadow-sm group h-[48px] {(currentRoute === '/analytics') ? 'bg-[#443C68]/10 border-[#443C68]/30' : ''}"
          title="Analytics"
        >
          {#if (isSidebarHovered || sidebarView !== 'menu')}
            <div class="flex items-center gap-3">
              <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span class="font-medium text-[#37352F] whitespace-nowrap">Analytics</span>
            </div>
            <svg class="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
          {:else}
            <svg class="w-5 h-5 text-[#443C68] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          {/if}
        </button>
      </div>
    </div>
  {:else if sidebarView === 'chat'}
    <!-- Chat History View -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Back Button and Header -->
      <div class="px-6 pt-4 pb-2 border-b border-gray-200">
        <button
          onclick={() => sidebarView = 'menu'}
          class="flex items-center gap-2 text-sm text-gray-600 hover:text-[#443C68] transition-colors mb-4"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </button>
        <h3 class="text-sm font-semibold text-[#37352F] uppercase tracking-wide">
          Chat History
        </h3>
      </div>

      <!-- New Chat Button -->
      <div class="p-6 border-b border-gray-100">
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
          class="group relative w-full p-4 rounded-xl hover:bg-white transition-all duration-200 {currentChatSession?.id ===
          session.id
            ? 'bg-white shadow-sm border border-[#443C68]/20'
            : ''}"
        >
          <button
            onclick={() => {
              onToggleDropdown(-1, new MouseEvent('click'));
              onLoadSession(session);
            }}
            class="w-full text-left"
          >
            <div class="text-sm font-medium text-[#37352F] truncate mb-2">
              {session.title}
            </div>
            <div
              class="flex items-center justify-between text-xs text-gray-500"
            >
              <span>{new Date(session.created_at).toLocaleDateString()}</span>
              <span
                class="bg-[#443C68]/10 text-[#443C68] px-2.5 py-1 rounded-full font-medium"
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
              class="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
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
                class="absolute right-0 mt-1 w-40 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50"
                role="menu"
                onclick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  onclick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(session.id);
                  }}
                  class="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors flex items-center gap-2"
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
      <div class="px-6 pt-4 pb-2 border-b border-gray-200">
        <button
          onclick={() => sidebarView = 'menu'}
          class="flex items-center gap-2 text-sm text-gray-600 hover:text-[#443C68] transition-colors mb-4"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </button>
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-[#37352F] uppercase tracking-wide">
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
          <div class="px-6 pt-4 pb-3 border-b border-gray-200">
            <!-- Single line: Search, Filter dropdown, Sort order -->
            <div class="flex items-center gap-2">
              <!-- Search Input -->
              <div class="relative flex-1">
                <input
                  type="text"
                  placeholder="Search"
                  bind:value={searchQuery}
                  class="w-full px-3 py-2 pl-9 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#443C68] focus:border-transparent"
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
                  class="px-3 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center justify-center"
                  title="Filter & Sort"
                  aria-label="Filter and sort options"
                >
                  <svg class="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                  </svg>
                </button>

                <!-- Filter Dropdown Menu -->
                {#if showFilterDropdown}
                  <div
                    class="absolute right-0 mt-1 w-56 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50"
                    role="menu"
                    onclick={(e) => e.stopPropagation()}
                  >
                    <!-- Filter by Type Section -->
                    <div class="px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide border-b border-gray-100">
                      Filter by Type
                    </div>
                    <button
                      type="button"
                      onclick={() => {
                        filterType = 'all';
                        showFilterDropdown = false;
                      }}
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-between {filterType === 'all' ? 'bg-gray-50 text-[#443C68] font-medium' : ''}"
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
                        class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-between {filterType === String(type) ? 'bg-gray-50 text-[#443C68] font-medium' : ''}"
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
                    <div class="px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide border-t border-gray-100 mt-1">
                      Sort by
                    </div>
                    <button
                      type="button"
                      onclick={() => {
                        sortBy = 'name';
                        showFilterDropdown = false;
                      }}
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-between {sortBy === 'name' ? 'bg-gray-50 text-[#443C68] font-medium' : ''}"
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
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-between {sortBy === 'type' ? 'bg-gray-50 text-[#443C68] font-medium' : ''}"
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
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-between {sortBy === 'size' ? 'bg-gray-50 text-[#443C68] font-medium' : ''}"
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
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-between {sortBy === 'date' ? 'bg-gray-50 text-[#443C68] font-medium' : ''}"
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
                      class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-between {sortBy === 'chunks' ? 'bg-gray-50 text-[#443C68] font-medium' : ''}"
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
                class="px-3 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center justify-center"
                title={sortOrder === 'asc' ? 'Ascending' : 'Descending'}
              >
                {#if sortOrder === 'asc'}
                  <svg class="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12" />
                  </svg>
                {:else}
                  <svg class="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
          <div class="space-y-2">
            {#each filteredAndSortedDocuments as doc}
              <button
                onclick={() => onDocumentClick(doc)}
                class="w-full text-left bg-white p-3 rounded-lg border border-gray-200 hover:border-[#443C68] transition-colors cursor-pointer"
              >
                <div class="flex items-start gap-3">
                  <div class="flex-shrink-0">
                    {#if doc.file_type === 'pdf'}
                      <svg class="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm12 12H4l4-8 3 6 2-4 3 6z"></path>
                      </svg>
                    {:else if doc.file_type === 'docx'}
                      <svg class="w-5 h-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M9 2a2 2 0 00-2 2v8a2 2 0 002 2h6a2 2 0 002-2V6.414A2 2 0 0016.414 5L14 2.586A2 2 0 0012.586 2H9z"></path>
                      </svg>
                    {:else}
                      <svg class="w-5 h-5 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd"></path>
                      </svg>
                    {/if}
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium text-[#37352F] truncate" title={doc.file_path}>
                      {doc.file_path?.split('\\').pop() || doc.file_path?.split('/').pop() || 'Unknown'}
                    </div>
                    <div class="flex items-center gap-2 mt-1 text-xs text-gray-500">
                      <span class="uppercase">{doc.file_type}</span>
                      <span>•</span>
                      <span>{doc.chunks_count || 0} chunks</span>
                      {#if doc.file_size}
                        <span>•</span>
                        <span>{(doc.file_size / 1024).toFixed(1)} KB</span>
                      {/if}
                    </div>
                  </div>
                </div>
              </button>
            {/each}
          </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</div>

