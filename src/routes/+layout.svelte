<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import { cubicOut } from 'svelte/easing';

  // Width-based transition so the chat area reflows smoothly alongside the panel
  function slideWidth(node: HTMLElement, { duration = 240, easing = cubicOut }: { duration?: number; easing?: (t: number) => number } = {}) {
    const w = node.getBoundingClientRect().width || 480;
    return {
      duration,
      easing,
      css: (t: number) => `width: ${w * t}px; min-width: 0; overflow: hidden;`,
    };
  }
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import { apiService } from '$lib/api/services';
  import { createApiRequest } from '$lib/utils/api';
  import { initTheme } from '$lib/stores/theme';
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
  import FileTypeIcon from '$lib/components/FileTypeIcon.svelte';
  import { getFileTypeConfig } from '$lib/utils/fileTypes';

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
      initTheme();
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
  // Set to true while the content-refresh interval is active; prevents loadIndexedDocumentsCore
  // from re-enabling contentIndexingInProgress after the interval has decided to stop.
  let contentPollingActive = false;

  function startUpdateQueuePolling() {
    // Close any existing SSE connection before opening a new one to prevent stale handlers
    // from firing with old lastProcessingCount state and prematurely clearing the interval.
    if (updateEventSource) {
      updateEventSource.close();
      updateEventSource = null;
    }
    // Use SSE (Server-Sent Events) for push-based updates - no polling
    try {
      updateEventSource = apiService.createUpdateStream((data) => {
        if (data?.queue) {
          const currentCompleted = data.queue.completed || 0;
          const currentProcessing = data.queue.processing || 0;

          // Only act on "processing finished" when we observed it actually processing.
          // Avoids clearing the content-refresh interval on stale queue data from a
          // prior session when the SSE first connects.
          if (lastProcessingCount > 0 && currentProcessing === 0) {
            lastCompletedCount = currentCompleted;
            console.debug('All updates finished, scheduling one document list refresh');
            if (contentRefreshIntervalId) {
              clearInterval(contentRefreshIntervalId);
              contentRefreshIntervalId = null;
            }
            contentPollingActive = false;
            contentIndexingInProgress.set(false);
            if (refreshTimeout) clearTimeout(refreshTimeout);
            refreshTimeout = setTimeout(() => {
              refreshTimeout = null;
              loadIndexedDocuments();
            }, 1500);
          } else if (currentCompleted > lastCompletedCount) {
            lastCompletedCount = currentCompleted;
            // During incremental updates, refresh once when a file finishes processing
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
    contentPollingActive = false;
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
      // Only re-enable the progress banner if polling is still active; prevents a
      // trailing debounced load from resurrecting the flag after hitMax/stuckMetadataOnly.
      if (metadataOnlyCount > 0 && contentPollingActive) {
        contentIndexingInProgress.set(true);
      } else if (indexedCount > 0 || total === 0) {
        // Also clear when directory has no supported files — nothing to wait for.
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

  /**
   * Immediate document list refresh for explicit user-triggered file operations
   * (rename, delete, move). Cancels any pending debounced load so the result
   * appears right away instead of being blocked by the 2.5s SSE debounce.
   */
  function forceRefreshDocuments() {
    if (documentLoadScheduled) {
      clearTimeout(documentLoadScheduled);
      documentLoadScheduled = null;
    }
    if (isLoadingDocuments) {
      loadRequestedWhileLoading = true;
      return;
    }
    loadIndexedDocumentsCore();
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
      contentPollingActive = false; // will be set true when the interval starts below
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

          // set_directory awaits initialize_from_directory synchronously, so by the time
          // loadIndexedDocumentsCore returns we already have the definitive initial state:
          // - 0 docs  → no supported files (or empty dir); nothing to poll for
          // - all indexed (no metadata_only) → resume mode, already done
          // - has metadata_only → background indexing is in progress; start the interval
          const hasMetadataOnly = indexedDocuments.some(
            (d: any) => d.processing_status === 'metadata_only'
          );

          startUpdateQueuePolling(); // SSE for incremental file-watcher updates always needed

          if (!hasMetadataOnly) {
            // Nothing is pending — skip the interval entirely
            return;
          }

          let refreshCount = 0;
          const maxRefreshes = 200; // 10-minute absolute ceiling
          const noProgressTicksBeforeStop = 10; // 30s without a new indexed doc → give up (all done)
          const zeroIndexedGiveUpTicks = 10; // ~30s with 0 indexed docs → give up
          const stuckMetadataOnlyTicks = 20; // ~60s with metadata_only and no progress → give up
          let previousIndexedCount = indexedDocuments.filter(
            (doc: any) => doc.processing_status === 'indexed'
          ).length;
          let noProgressTicks = 0;

          contentPollingActive = true;
          contentRefreshIntervalId = setInterval(async () => {
            if (!contentRefreshIntervalId) return;
            refreshCount++;
            loadIndexedDocuments(); // debounced

            // Fetch accurate progress from backend (not limited to 100-doc sample)
            try {
              const prog = await apiService.getIndexingProgress();
              if (prog) {
                indexingProgress.set({ indexed: prog.processed, total: prog.total });
              }
            } catch (_) { /* non-critical — UI falls back to document list counts */ }

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
            const stuck = noProgressTicks >= noProgressTicksBeforeStop && total > 0 && metadataOnlyCount === 0;
            const hitMax = refreshCount >= maxRefreshes;
            const giveUpZeroIndexed = currentIndexedCount === 0 && total > 0 && noProgressTicks >= zeroIndexedGiveUpTicks;
            const stuckMetadataOnly = metadataOnlyCount > 0 && noProgressTicks >= stuckMetadataOnlyTicks;

            if (allIndexed || stuck || hitMax || giveUpZeroIndexed || stuckMetadataOnly) {
              if (contentRefreshIntervalId) clearInterval(contentRefreshIntervalId);
              contentRefreshIntervalId = null;
              contentPollingActive = false;
              contentIndexingInProgress.set(false);
            }
          }, 3000);
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

  let documentReloadKey = $state(0);
  let viewerSearchText = $state('');
  let viewerPageNumber = $state<number | null>(null);

  function handleDocumentClick(document: any) {
    selectedDocument = document;
    viewerSearchText = '';
    viewerPageNumber = null;
  }

  function handleCloseDocumentViewer() {
    selectedDocument = null;
    viewerSearchText = '';
    viewerPageNumber = null;
  }

  // "Change Directory" from chat page: show directory picker in main area
  onMount(() => {
    const handleRequestChangeFolder = () => {
      wantsToChangeFolder = true;
    };
    window.addEventListener('openDirectoryModalFromLayout', handleRequestChangeFolder);

    const handleEditApplied = () => {
      forceRefreshDocuments();
      documentReloadKey += 1;
    };
    window.addEventListener('editApplied', handleEditApplied);

    const handleFileDeleted = (e: Event) => {
      const detail = (e as CustomEvent<{ filePath: string }>).detail;
      if (selectedDocument && selectedDocument.file_path === detail.filePath) {
        selectedDocument = null;
      }
      forceRefreshDocuments();
    };
    window.addEventListener('fileDeleted', handleFileDeleted);

    const handleFileModified = (e: Event) => {
      const detail = (e as CustomEvent<{ oldPath: string; newPath: string }>).detail;
      // Update the document viewer if the modified file is currently open
      if (selectedDocument && selectedDocument.file_path === detail.oldPath) {
        if (detail.newPath) {
          selectedDocument = { ...selectedDocument, file_path: detail.newPath };
          documentReloadKey += 1;
        } else {
          selectedDocument = null;
        }
      }
      forceRefreshDocuments();
    };
    window.addEventListener('fileModified', handleFileModified);

    // Source chip click from chat: open the document viewer at the relevant snippet.
    const handleOpenDocumentViewer = (e: Event) => {
      const { filePath, searchText: snippet, pageNumber } = (e as CustomEvent<{ filePath: string; searchText: string; pageNumber?: number | null }>).detail;
      const doc = indexedDocuments.find((d: any) => d.file_path === filePath);
      if (doc) {
        selectedDocument = doc;
        viewerSearchText = snippet ?? '';
        viewerPageNumber = pageNumber ?? null;
        documentReloadKey += 1;
      }
    };
    window.addEventListener('openDocumentViewer', handleOpenDocumentViewer);

    return () => {
      window.removeEventListener('openDirectoryModalFromLayout', handleRequestChangeFolder);
      window.removeEventListener('editApplied', handleEditApplied);
      window.removeEventListener('fileDeleted', handleFileDeleted);
      window.removeEventListener('fileModified', handleFileModified);
      window.removeEventListener('openDocumentViewer', handleOpenDocumentViewer);
    };
  });

  const showDirectoryPicker = $derived(!$systemStatus?.directory_set || wantsToChangeFolder);
</script>

<svelte:head>
  <title>Klair AI</title>
  <!-- UI font: must match --font-sans in app.css (font name + weights you use) -->
  <link
    href="https://fonts.googleapis.com/css2?family=Figtree:wght@300;400;500;600;700&display=swap"
    rel="stylesheet"
  />
</svelte:head>

<div class="h-screen font-sans bg-white dark:bg-gray-950 overflow-hidden flex flex-col">
  <!-- Global API error banner (e.g. rate limit, set directory failure) -->
  {#if $apiError}
    <div class="flex-shrink-0 bg-amber-50 dark:bg-amber-950/40 border-b border-amber-200 dark:border-amber-900/60 px-4 py-2 flex items-center justify-between gap-3">
      <p class="text-sm text-amber-800 dark:text-amber-200 flex-1 truncate">{$apiError}</p>
      <button
        type="button"
        onclick={() => apiActions.clearError()}
        class="flex-shrink-0 text-amber-600 hover:text-amber-800 dark:text-amber-200 dark:hover:text-amber-100 p-1"
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
      workspaceRoot={$systemStatus?.current_directory ?? ''}
      currentChatSession={$currentChatSession}
      isLoadingDocuments={isLoadingDocuments}
      isIndexingInProgress={isIndexingInProgress}
      contentIndexingInProgress={$contentIndexingInProgress}
      indexingProgress={$indexingProgress}
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
      onRefreshDocuments={forceRefreshDocuments}
      collapsed={!!selectedDocument}
    />

    <!-- Main Content Area -->
    <div class="flex-1 flex overflow-hidden relative">

      <!-- Document panel — sits immediately right of the sidebar -->
      {#if selectedDocument}
        <div
          transition:slideWidth={{ duration: 240, easing: cubicOut }}
          class="flex flex-col bg-white dark:bg-gray-950 border-r border-gray-200 dark:border-gray-800 overflow-hidden flex-shrink-0"
          style="width: 560px; min-width: 360px; max-width: 55vw;"
        >
          <!-- Panel header -->
          <div class="flex-shrink-0 bg-white dark:bg-gray-950 border-b border-gray-200 dark:border-gray-800 px-4 py-3 flex items-center gap-3">
            <div class="flex-shrink-0">
              <FileTypeIcon fileType={selectedDocument.file_type} class="w-5 h-5 flex-shrink-0" />
            </div>
            <div class="flex-1 min-w-0">
              <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100 truncate">
                {selectedDocument.file_path?.split('\\').pop() || selectedDocument.file_path?.split('/').pop() || 'Unknown'}
              </h2>
              <div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5 flex items-center gap-1.5">
                <span>{getFileTypeConfig(selectedDocument.file_type).label}</span>
                {#if selectedDocument.file_size}
                  <span>·</span>
                  <span>{(selectedDocument.file_size / 1024).toFixed(1)} KB</span>
                {/if}
              </div>
            </div>
            <button
              onclick={handleCloseDocumentViewer}
              class="flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors text-gray-500 dark:text-gray-400"
              aria-label="Close document panel"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Panel content -->
          <div class="flex-1 overflow-hidden">
            {#key documentReloadKey}
              <DocumentViewer document={selectedDocument as any} searchText={viewerSearchText} pageNumber={viewerPageNumber} />
            {/key}
          </div>
        </div>
      {/if}

      <!-- Chat / route content — always rendered, fills remaining space -->
      <div class="flex-1 flex flex-col bg-white dark:bg-gray-950 overflow-y-auto overflow-x-hidden min-w-0">
        {#if showDirectoryPicker}
          <DirectorySelection
            isSetting={isSettingDirectory}
            allowCancel={$systemStatus?.directory_set ?? false}
            on:select={handleDirectorySelect}
            on:cancel={() => {
              wantsToChangeFolder = false;
            }}
          />
        {:else}
          {@render children()}
        {/if}
      </div>

    </div>
  </div>
</div>

