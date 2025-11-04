<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import { apiService } from '$lib/api/services';
  import { createApiRequest } from '$lib/utils/api';
  import {
    systemStatus,
    currentChatSession,
    chatHistory,
  } from '$lib/stores/api';
  import DirectorySelectionModal from '$lib/components/DirectorySelectionModal.svelte';

  let { children } = $props();

  // Shared state for sidebar (using $state for reactivity in runes mode)
  let indexedDocuments = $state<any[]>([]);
  let isLoadingDocuments = $state(false);
  let isIndexingInProgress = $state(false);
  let openDropdownId = $state<number | null>(null);
  let isInitializing = $state(true);
  let isSettingDirectory = $state(false);
  let showDirectoryModal = $state(false);
  let hasAutoOpenedModal = $state(false);
  let userCancelledModal = $state(false);

  // Initialize system status on mount
  onMount(() => {
    (async () => {
      await testConnection();
      if (!$systemStatus?.directory_set) {
        showDirectoryModal = true;
      } else {
        await loadChatHistory();
        await loadIndexedDocuments();
      }
      isInitializing = false;
    })();
  });

  async function testConnection() {
    await createApiRequest(async () => {
      const status = await apiService.getStatus();
      systemStatus.set(status);
      return status;
    }, "Backend connection test");
  }

  async function loadChatHistory() {
    try {
      const sessions = await apiService.getChatSessions();
      chatHistory.set(sessions);
    } catch (error) {
      console.error('Failed to load chat history:', error);
    }
  }

  async function loadIndexedDocuments() {
    isLoadingDocuments = true;
    try {
      const response = await apiService.searchDocuments({ limit: 100 });
      indexedDocuments = response.documents?.documents || [];
    } catch (error) {
      console.error('Failed to load documents:', error);
      indexedDocuments = [];
    } finally {
      isLoadingDocuments = false;
    }
  }

  async function handleDirectorySelect(event: CustomEvent<{ directoryPath: string }>) {
    const directoryPath = event.detail.directoryPath;
    if (!directoryPath.trim()) return;
    
    isSettingDirectory = true;
    try {
      await apiService.setDirectory(directoryPath);
      await testConnection();
      await loadChatHistory();
      await loadIndexedDocuments();
      showDirectoryModal = false;
      
      // Auto-refresh documents as they're being indexed
      isIndexingInProgress = true;
      let refreshCount = 0;
      const maxRefreshes = 15;
      let previousCount = indexedDocuments.length;
      
      const refreshInterval = setInterval(async () => {
        refreshCount++;
        await loadIndexedDocuments();
        
        const hasNewDocs = indexedDocuments.length > previousCount;
        if (hasNewDocs) {
          previousCount = indexedDocuments.length;
        }
        
        if (refreshCount >= maxRefreshes || (!hasNewDocs && refreshCount > 3)) {
          isIndexingInProgress = false;
          clearInterval(refreshInterval);
        }
      }, 2000);
    } catch (error) {
      console.error('Failed to set directory:', error);
    } finally {
      isSettingDirectory = false;
    }
  }

  function startNewChat() {
    if ($page.url.pathname === '/') {
      // If on home page, just clear session
      currentChatSession.set(null);
    } else {
      goto('/');
    }
  }

  function handleChatClick() {
    goto('/');
  }

  async function handleLoadSession(session: any) {
    if ($page.url.pathname === '/') {
      currentChatSession.set(session);
      // Dispatch event for +page.svelte to handle message loading
      window.dispatchEvent(new CustomEvent('loadSession', { detail: session }));
    } else {
      goto('/');
    }
  }

  async function handleDeleteSession(sessionId: number) {
    await createApiRequest(async () => {
      await apiService.deleteChatSession(sessionId);
      if ($currentChatSession?.id === sessionId) {
        currentChatSession.set(null);
      }
      await loadChatHistory();
      openDropdownId = null;
      return true;
    }, "Delete session");
  }

  function handleToggleDropdown(sessionId: number, event: MouseEvent) {
    event.stopPropagation();
    openDropdownId = openDropdownId === sessionId ? null : sessionId;
  }

  // Reactive statement for modal auto-open using $effect (runes mode)
  $effect(() => {
    if (!isInitializing && !hasAutoOpenedModal && !userCancelledModal && $systemStatus && !$systemStatus.directory_set && !showDirectoryModal) {
      showDirectoryModal = true;
      hasAutoOpenedModal = true;
    }
    if ($systemStatus?.directory_set) {
      userCancelledModal = false;
    }
  });
</script>

<svelte:head>
  <title>Klair AI</title>
  <link
    href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap"
    rel="stylesheet"
  />
</svelte:head>

<div class="h-screen bg-white font-['Inter'] overflow-hidden flex flex-col">
  <!-- Directory Selection Modal -->
  <DirectorySelectionModal
    bind:isOpen={showDirectoryModal}
    isSetting={isSettingDirectory}
    allowCancel={$systemStatus?.directory_set || false}
    on:select={handleDirectorySelect}
    on:cancel={() => {
      showDirectoryModal = false;
      userCancelledModal = true;
    }}
  />

  <!-- Block main content if no directory is set and modal is not open -->
  {#if !isInitializing && !$systemStatus?.directory_set && !showDirectoryModal}
    <div class="fixed inset-0 bg-black bg-opacity-20 z-40"></div>
  {/if}

  <!-- Top Navigation -->
  <div class="bg-white px-6 py-4 absolute top-3 right-5 z-10">
    <div class="flex items-center gap-4">
      <div class="text-sm text-[#37352F] bg-[#F7F7F7] px-4 py-2 rounded-lg flex items-center gap-2">
        {#if $systemStatus?.directory_set}
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>  
          /{$systemStatus.current_directory?.split("\\").pop()}
        {:else}
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg> 
          No directory set
        {/if}
      </div>

      {#if $systemStatus?.directory_set}
        <button
          type="button"
          onclick={() => showDirectoryModal = true}
          class="px-6 py-2.5 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          disabled={isSettingDirectory || isInitializing}
          aria-label="Change document directory"
        >
          Change Directory
        </button>
      {/if}
    </div>
  </div>

  <div class="flex flex-1 overflow-hidden">
    <Sidebar
      currentRoute={$page.url.pathname}
      chatHistory={$chatHistory}
      indexedDocuments={indexedDocuments}
      currentChatSession={$currentChatSession}
      isLoadingDocuments={isLoadingDocuments}
      isIndexingInProgress={isIndexingInProgress}
      openDropdownId={openDropdownId}
      onNewChat={startNewChat}
      onChatClick={handleChatClick}
      onDocumentsClick={() => {
        if (indexedDocuments.length === 0) {
          loadIndexedDocuments();
        }
      }}
      onLoadSession={handleLoadSession}
      onDeleteSession={handleDeleteSession}
      onToggleDropdown={handleToggleDropdown}
    />

    <!-- Main Content Area -->
    <div class="flex-1 flex flex-col bg-white overflow-y-auto">
{@render children()}
    </div>
  </div>
</div>
