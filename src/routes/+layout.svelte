<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import { apiService } from '$lib/api/services';
  import { createApiRequest } from '$lib/utils/api';
  import {
    systemStatus,
    currentChatSession,
    chatHistory,
    isIndexingInProgress as isIndexingInProgressStore,
    contentIndexingInProgress,
    metadataIndexed,
    updateQueueStatus,
  } from '$lib/stores/api';
  import DirectorySelectionModal from '$lib/components/DirectorySelectionModal.svelte';
  import DocumentViewer from '$lib/components/DocumentViewer.svelte';

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
  let selectedDocument = $state<any | null>(null);

  // Initialize system status on mount
  onMount(() => {
    (async () => {
      await testConnection();
      if (!$systemStatus?.directory_set) {
        showDirectoryModal = true;
      } else {
        await loadChatHistory();
        await loadIndexedDocuments();
        // Phase 3: Start SSE stream for update queue status (no polling)
        startUpdateQueuePolling();
      }
      isInitializing = false;
    })();
  });

  // Phase 3: Real-time update queue status via Server-Sent Events (SSE)
  // No polling - uses push-based SSE for efficient real-time updates
  let updateEventSource: EventSource | null = null;
  let lastCompletedCount = 0; // Track completed updates to detect new documents
  let lastProcessingCount = 0; // Track processing to detect when updates finish
  let refreshTimeout: ReturnType<typeof setTimeout> | null = null; // Debounce refresh
  
  function startUpdateQueuePolling() {
    // Use SSE (Server-Sent Events) for push-based updates - no polling
    try {
      updateEventSource = apiService.createUpdateStream((data) => {
        if (data?.queue) {
          const currentCompleted = data.queue.completed || 0;
          const currentProcessing = data.queue.processing || 0;
          
          // Check if updates completed (new documents indexed)
          if (currentCompleted > lastCompletedCount) {
            // New documents were indexed - refresh the document list
            console.debug(`Updates completed: ${currentCompleted} (was ${lastCompletedCount}), refreshing document list`);
            // Debounce refresh to avoid multiple rapid refreshes
            if (refreshTimeout) clearTimeout(refreshTimeout);
            refreshTimeout = setTimeout(() => {
              loadIndexedDocuments();
            }, 500); // Small delay to ensure database is updated
            lastCompletedCount = currentCompleted;
          } else if (currentCompleted > 0 && lastCompletedCount === 0) {
            // Initialize the count on first SSE message
            lastCompletedCount = currentCompleted;
          }
          
          // Also refresh when processing drops from >0 to 0 (all updates finished)
          if (lastProcessingCount > 0 && currentProcessing === 0) {
            // All updates finished - refresh to catch any new documents
            console.debug('All updates finished, refreshing document list');
            if (refreshTimeout) clearTimeout(refreshTimeout);
            refreshTimeout = setTimeout(() => {
              loadIndexedDocuments();
            }, 1000); // Small delay to ensure database is updated
          }
          
          // Fallback: If updates just started (processing went from 0 to >0),
          // refresh after a delay to catch new files that are being indexed
          if (lastProcessingCount === 0 && currentProcessing > 0) {
            // Updates just started - refresh after a delay to catch new files
            console.debug('Updates started, will refresh document list when complete');
            if (refreshTimeout) clearTimeout(refreshTimeout);
            refreshTimeout = setTimeout(() => {
              loadIndexedDocuments();
            }, 3000); // Refresh 3 seconds after updates start (gives time for indexing)
          }
          
          lastProcessingCount = currentProcessing;
          
          updateQueueStatus.set({
            pending: data.queue.pending || 0,
            processing: currentProcessing,
            completed: currentCompleted,
            failed: data.queue.failed || 0,
          });
        }
      });
      
      if (updateEventSource) {
        // Monitor SSE connection for errors
        updateEventSource.addEventListener('error', (error) => {
          console.warn('SSE connection error, will attempt to reconnect:', error);
          // EventSource automatically reconnects, so we just log the error
        });
        
        // Log successful connection
        updateEventSource.addEventListener('open', () => {
          console.debug('SSE connection established for update queue status');
        });
      } else {
        console.warn('Failed to create SSE stream - update status will not be available');
        // Set status to null to indicate it's not available
        updateQueueStatus.set(null);
      }
    } catch (error) {
      // SSE not supported or failed
      console.warn('SSE not available - update status will not be displayed:', error);
      updateQueueStatus.set(null);
    }
  }

  onDestroy(() => {
    // Clean up SSE connection
    if (updateEventSource) {
      updateEventSource.close();
      updateEventSource = null;
    }
    // Clean up refresh timeout
    if (refreshTimeout) {
      clearTimeout(refreshTimeout);
    }
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
      
      // Check indexing status
      const metadataOnlyCount = indexedDocuments.filter(
        (doc: any) => doc.processing_status === 'metadata_only'
      ).length;
      const indexedCount = indexedDocuments.filter(
        (doc: any) => doc.processing_status === 'indexed'
      ).length;
      
      // Metadata is indexed if we have any documents
      if (indexedDocuments.length > 0) {
        metadataIndexed.set(true);
      }
      
      // Content indexing is in progress if we have metadata_only documents
      if (metadataOnlyCount > 0) {
        contentIndexingInProgress.set(true);
      } else if (indexedCount > 0) {
        // All documents are fully indexed
        contentIndexingInProgress.set(false);
        isIndexingInProgressStore.set(false);
      }
      
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
      
      // Metadata indexing happens instantly (< 1 second)
      // Wait a moment for metadata to be indexed
      await new Promise(resolve => setTimeout(resolve, 500));
      await loadIndexedDocuments();
      
      showDirectoryModal = false;
      
      // Metadata is now indexed - allow queries immediately
      metadataIndexed.set(true);
      isIndexingInProgress = false; // Don't block queries
      isIndexingInProgressStore.set(false);
      
      // Reset completed count tracker for new directory
      lastCompletedCount = 0;
      lastProcessingCount = 0;
      
      // Monitor content indexing progress in background
      let refreshCount = 0;
      const maxRefreshes = 30; // Monitor longer for content indexing
      let previousIndexedCount = indexedDocuments.filter(
        (doc: any) => doc.processing_status === 'indexed'
      ).length;
      
      const refreshInterval = setInterval(async () => {
        refreshCount++;
        await loadIndexedDocuments();
        
        const currentIndexedCount = indexedDocuments.filter(
          (doc: any) => doc.processing_status === 'indexed'
        ).length;
        
        const hasNewIndexed = currentIndexedCount > previousIndexedCount;
        if (hasNewIndexed) {
          previousIndexedCount = currentIndexedCount;
        }
        
        // Stop monitoring if all documents are indexed or max refreshes reached
        const metadataOnlyCount = indexedDocuments.filter(
          (doc: any) => doc.processing_status === 'metadata_only'
        ).length;
        
        if (metadataOnlyCount === 0 || refreshCount >= maxRefreshes) {
          contentIndexingInProgress.set(false);
          clearInterval(refreshInterval);
        }
      }, 3000); // Check every 3 seconds for content indexing progress
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

  function handleDocumentClick(document: any) {
    selectedDocument = document;
  }

  function handleCloseDocumentViewer() {
    selectedDocument = null;
  }

  // Listen for directory modal open event from chat page
  onMount(() => {
    const handleOpenModal = () => {
      showDirectoryModal = true;
    };
    window.addEventListener('openDirectoryModalFromLayout', handleOpenModal);
    return () => {
      window.removeEventListener('openDirectoryModalFromLayout', handleOpenModal);
    };
  });

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
    href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap"
    rel="stylesheet"
  />
</svelte:head>

<div class="h-screen bg-white overflow-hidden flex flex-col">
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

  <div class="flex flex-1 overflow-hidden">
    <Sidebar
      currentRoute={$page.url.pathname}
      chatHistory={$chatHistory}
      indexedDocuments={indexedDocuments}
      currentChatSession={$currentChatSession}
      isLoadingDocuments={isLoadingDocuments}
      isIndexingInProgress={isIndexingInProgress}
      contentIndexingInProgress={$contentIndexingInProgress}
      metadataIndexed={$metadataIndexed}
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
      onDocumentClick={handleDocumentClick}
    />

    <!-- Main Content Area -->
    <div class="flex-1 flex flex-col bg-white overflow-y-auto relative">
      {#if selectedDocument}
        <!-- Document Viewer Overlay -->
        <div class="absolute inset-0 z-50 bg-white flex flex-col">
          <!-- Document Viewer Header -->
          <div class="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="flex-shrink-0">
                {#if selectedDocument.file_type === 'pdf'}
                  <svg class="w-6 h-6 text-red-500" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm12 12H4l4-8 3 6 2-4 3 6z"></path>
                  </svg>
                {:else if selectedDocument.file_type === 'docx'}
                  <svg class="w-6 h-6 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M9 2a2 2 0 00-2 2v8a2 2 0 002 2h6a2 2 0 002-2V6.414A2 2 0 0016.414 5L14 2.586A2 2 0 0012.586 2H9z"></path>
                  </svg>
                {:else}
                  <svg class="w-6 h-6 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd"></path>
                  </svg>
                {/if}
              </div>
              <div>
                <h2 class="text-lg font-semibold text-[#37352F] truncate max-w-2xl">
                  {selectedDocument.file_path?.split('\\').pop() || selectedDocument.file_path?.split('/').pop() || 'Unknown'}
                </h2>
                <div class="text-xs text-gray-500 mt-1">
                  <span class="uppercase">{selectedDocument.file_type}</span>
                  {#if selectedDocument.file_size}
                    <span> • {(selectedDocument.file_size / 1024).toFixed(1)} KB</span>
                  {/if}
                </div>
              </div>
            </div>
            <button
              onclick={handleCloseDocumentViewer}
              class="flex items-center justify-center w-10 h-10 rounded-lg hover:bg-gray-100 transition-colors text-gray-600 hover:text-[#443C68]"
              aria-label="Close document viewer"
            >
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
              </svg>
            </button>
          </div>

          <!-- Document Viewer Content -->
          <div class="flex-1 overflow-hidden">
            <DocumentViewer document={selectedDocument as any} />
          </div>
        </div>
      {:else}
{@render children()}
      {/if}
    </div>
  </div>
</div>
