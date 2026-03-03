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
    apiActions,
    error as apiError,
    indexingProgress,
  } from '$lib/stores/api';
  import DirectorySelection from '$lib/components/DirectorySelection.svelte';
  import DocumentViewer from '$lib/components/DocumentViewer.svelte';

  let { children } = $props();

  // Shared state for sidebar (using $state for reactivity in runes mode)
  let indexedDocuments = $state<any[]>([]);
  let isLoadingDocuments = $state(false);
  let isIndexingInProgress = $state(false);
  let openDropdownId = $state<number | null>(null);
  let isInitializing = $state(true);
  let isSettingDirectory = $state(false);
  /** When true, show directory picker in main area (e.g. after "Change Directory"). */
  let wantsToChangeFolder = $state(false);
  let selectedDocument = $state<any | null>(null);

  // Initialize system status on mount
  onMount(() => {
    (async () => {
      await testConnection();
      if ($systemStatus?.directory_set) {
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

  // Prevent document-load storm: debounce and single interval only
  const DOCUMENT_LOAD_DEBOUNCE_MS = 2500;
  let lastDocumentLoadTime = 0;
  let documentLoadScheduled: ReturnType<typeof setTimeout> | null = null;
  let contentRefreshIntervalId: ReturnType<typeof setInterval> | null = null;
  let loadRequestedWhileLoading = false; // Request one more load after current finishes

  function startUpdateQueuePolling() {
    // Use SSE (Server-Sent Events) for push-based updates - no polling
    try {
      updateEventSource = apiService.createUpdateStream((data) => {
        if (data?.queue) {
          const currentCompleted = data.queue.completed || 0;
          const currentProcessing = data.queue.processing || 0;
          
          // Single coalesced refresh: prefer "all updates finished" to avoid storm
          if (lastProcessingCount > 0 && currentProcessing === 0) {
            lastCompletedCount = currentCompleted;
            console.debug('All updates finished, scheduling one document list refresh');
            if (contentRefreshIntervalId) {
              clearInterval(contentRefreshIntervalId);
              contentRefreshIntervalId = null;
            }
            contentIndexingInProgress.set(false);
            if (refreshTimeout) clearTimeout(refreshTimeout);
            refreshTimeout = setTimeout(() => {
              refreshTimeout = null;
              loadIndexedDocuments();
            }, 1500);
          } else if (currentProcessing === 0 && currentCompleted > 0) {
            // Queue idle with work done – stop content-indexing polling so we don't loop forever
            if (contentRefreshIntervalId) {
              clearInterval(contentRefreshIntervalId);
              contentRefreshIntervalId = null;
            }
            contentIndexingInProgress.set(false);
          } else if (currentCompleted > lastCompletedCount) {
            lastCompletedCount = currentCompleted;
            // During indexing, only schedule a refresh if we don't already have one
            if (!refreshTimeout && currentProcessing > 0) {
              refreshTimeout = setTimeout(() => {
                refreshTimeout = null;
                loadIndexedDocuments();
              }, 2500);
            }
          } else if (currentCompleted > 0 && lastCompletedCount === 0) {
            lastCompletedCount = currentCompleted;
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
    if (updateEventSource) {
      updateEventSource.close();
      updateEventSource = null;
    }
    if (refreshTimeout) clearTimeout(refreshTimeout);
    if (documentLoadScheduled) clearTimeout(documentLoadScheduled);
    if (contentRefreshIntervalId) clearInterval(contentRefreshIntervalId);
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

  async function loadIndexedDocumentsCore() {
    isLoadingDocuments = true;
    loadRequestedWhileLoading = false;
    try {
      const response = await apiService.searchDocuments({ limit: 100 });
      indexedDocuments = response.documents?.documents || [];
      
      const metadataOnlyCount = indexedDocuments.filter(
        (doc: any) => doc.processing_status === 'metadata_only'
      ).length;
      const indexedCount = indexedDocuments.filter(
        (doc: any) => doc.processing_status === 'indexed'
      ).length;
      const total = indexedDocuments.length;

      indexingProgress.set({ indexed: indexedCount, total });

      if (indexedDocuments.length > 0) metadataIndexed.set(true);
      if (metadataOnlyCount > 0) contentIndexingInProgress.set(true);
      else if (indexedCount > 0) {
        contentIndexingInProgress.set(false);
        isIndexingInProgressStore.set(false);
      }
    } catch (error) {
      console.error('Failed to load documents:', error);
      indexedDocuments = [];
    } finally {
      isLoadingDocuments = false;
      lastDocumentLoadTime = Date.now();
      // Only chain one more load if something requested it and we're not already "all indexed"
      // (avoids request storm when we keep getting 0 indexed from stale responses)
      if (loadRequestedWhileLoading) {
        loadRequestedWhileLoading = false;
        const stillMetadataOnly = indexedDocuments.some(
          (d: any) => d.processing_status === 'metadata_only'
        );
        if (stillMetadataOnly) loadIndexedDocuments();
      }
    }
  }

  /** Debounced document list load; never runs concurrently to prevent request storm */
  function loadIndexedDocuments() {
    if (isLoadingDocuments) {
      loadRequestedWhileLoading = true;
      return;
    }
    const now = Date.now();
    const elapsed = now - lastDocumentLoadTime;
    if (documentLoadScheduled) return;
    if (elapsed >= DOCUMENT_LOAD_DEBOUNCE_MS || lastDocumentLoadTime === 0) {
      loadIndexedDocumentsCore();
      return;
    }
    const delay = DOCUMENT_LOAD_DEBOUNCE_MS - elapsed;
    documentLoadScheduled = setTimeout(() => {
      documentLoadScheduled = null;
      if (!isLoadingDocuments) loadIndexedDocumentsCore();
    }, delay);
  }

  async function handleDirectorySelect(event: CustomEvent<{ directoryPath: string }>) {
    const directoryPath = event.detail.directoryPath;
    if (!directoryPath.trim()) return;

    isSettingDirectory = true;
    try {
      await apiService.setDirectory(directoryPath);

      wantsToChangeFolder = false;
      isSettingDirectory = false;
      indexedDocuments = [];
      contentIndexingInProgress.set(true);
      indexingProgress.set({ indexed: 0, total: 0 });
      metadataIndexed.set(true);
      isIndexingInProgressStore.set(false);
      lastCompletedCount = 0;
      lastProcessingCount = 0;

      // Optimistic update so overlay and $effect don't reopen modal before testConnection() returns
      systemStatus.update((s) => {
        const prev = s ?? {
          directory_set: false,
          current_directory: null,
          processor_ready: false,
          file_monitor_status: '',
          database_stats: { total_documents: 0, status_breakdown: {}, type_breakdown: {} },
        };
        return { ...prev, directory_set: true, current_directory: directoryPath };
      });

      // Load data in background (don't block the UI)
      (async () => {
        try {
          if (contentRefreshIntervalId) {
            clearInterval(contentRefreshIntervalId);
            contentRefreshIntervalId = null;
          }
          if (documentLoadScheduled) {
            clearTimeout(documentLoadScheduled);
            documentLoadScheduled = null;
          }

          await testConnection();
          await loadChatHistory();
          await new Promise((r) => setTimeout(r, 200)); // Brief delay for backend metadata
          lastDocumentLoadTime = 0; // allow immediate first load
          await loadIndexedDocumentsCore();
          lastDocumentLoadTime = Date.now();

          let refreshCount = 0;
          const maxRefreshes = 30;
          const noProgressTicksBeforeStop = 3;
          const zeroIndexedGiveUpTicks = 10; // stop after ~30s with 0 indexed to avoid infinite loop
          let previousIndexedCount = indexedDocuments.filter(
            (doc: any) => doc.processing_status === 'indexed'
          ).length;
          let noProgressTicks = 0;

          contentRefreshIntervalId = setInterval(async () => {
            if (!contentRefreshIntervalId) return;
            refreshCount++;
            loadIndexedDocuments(); // debounced

            const currentIndexedCount = indexedDocuments.filter(
              (doc: any) => doc.processing_status === 'indexed'
            ).length;
            const metadataOnlyCount = indexedDocuments.filter(
              (doc: any) => doc.processing_status === 'metadata_only'
            ).length;

            if (currentIndexedCount > previousIndexedCount) {
              previousIndexedCount = currentIndexedCount;
              noProgressTicks = 0;
            } else if (indexedDocuments.length > 0) {
              noProgressTicks++;
            }

            const total = indexedDocuments.length;
            const allIndexed = metadataOnlyCount === 0 && total > 0;
            const stuck =
              noProgressTicks >= noProgressTicksBeforeStop &&
              total > 0 &&
              metadataOnlyCount === 0;
            const hitMax = refreshCount >= maxRefreshes;
            // Backend says done but we keep getting 0 indexed (stale/race): stop after N ticks to avoid infinite polling
            const giveUpZeroIndexed =
              currentIndexedCount === 0 &&
              total > 0 &&
              noProgressTicks >= zeroIndexedGiveUpTicks;

            if (allIndexed || stuck || hitMax || giveUpZeroIndexed) {
              if (contentRefreshIntervalId) clearInterval(contentRefreshIntervalId);
              contentRefreshIntervalId = null;
              contentIndexingInProgress.set(false);
            }
          }, 3000);

          startUpdateQueuePolling();
        } catch (e) {
          console.error('Background load after set-directory:', e);
        }
      })();
    } catch (error: any) {
      console.error('Failed to set directory:', error);
      apiActions.setError(error?.message ?? 'Failed to set directory');
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

  // "Change Directory" from chat page: show directory picker in main area
  onMount(() => {
    const handleRequestChangeFolder = () => {
      wantsToChangeFolder = true;
    };
    window.addEventListener('openDirectoryModalFromLayout', handleRequestChangeFolder);
    return () => {
      window.removeEventListener('openDirectoryModalFromLayout', handleRequestChangeFolder);
    };
  });

  const showDirectoryPicker = $derived(!$systemStatus?.directory_set || wantsToChangeFolder);
</script>

<svelte:head>
  <title>Klair AI</title>
  <link
    href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap"
    rel="stylesheet"
  />
</svelte:head>

<div class="h-screen bg-white overflow-hidden flex flex-col">
  <!-- Global API error banner (e.g. rate limit, set directory failure) -->
  {#if $apiError}
    <div class="flex-shrink-0 bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center justify-between gap-3">
      <p class="text-sm text-amber-800 flex-1 truncate">{$apiError}</p>
      <button
        type="button"
        onclick={() => apiActions.clearError()}
        class="flex-shrink-0 text-amber-600 hover:text-amber-800 p-1"
        aria-label="Dismiss"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
      </button>
    </div>
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
      {#if showDirectoryPicker}
        <DirectorySelection
          isSetting={isSettingDirectory}
          allowCancel={$systemStatus?.directory_set ?? false}
          on:select={handleDirectorySelect}
          on:cancel={() => {
            wantsToChangeFolder = false;
          }}
        />
      {:else if selectedDocument}
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
