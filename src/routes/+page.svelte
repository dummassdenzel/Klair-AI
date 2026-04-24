<script lang="ts">
  import { onMount, tick } from "svelte";
  import { apiService } from "$lib/api/services";
  import {
    systemStatus,
    currentChatSession,
    chatHistory,
    isChatLoading,
    apiActions,
    metadataIndexed,
    contentIndexingInProgress,
    indexingProgress,
  } from "$lib/stores/api";
  import type { ChatMessage } from "$lib/api/types";
  import MarkdownRenderer from "$lib/components/MarkdownRenderer.svelte";
  import FileTypeIcon from "$lib/components/FileTypeIcon.svelte";
  import EditProposalCard from "$lib/components/EditProposalCard.svelte";
import { getFileTypeConfig } from "$lib/utils/fileTypes";
  import { messageToConversationTitle } from "$lib/utils/chatTitle";
  import { formatCalendarDate } from "$lib/utils/dateFormat";
  import { theme } from "$lib/stores/theme";

  /** Watermark strength: 0 = invisible, 1 = solid. Edit only `light` and `dark` here. */
  const WATERMARK_OPACITY = { light: 0.12, dark: 0.12 } as const;

  /** Single scroll target: top of latest AI reply (or typing placeholder before first token). */
  const CHAT_SCROLL_ANCHOR_ID = "chat-scroll-target";

  let messages: ChatMessage[] = [];
  let expandedSources: Record<number, boolean> = {};
  let messagesContainer: HTMLDivElement;
  let shouldAutoScroll = true;
  /** Coalesce per-token scrolls to one rAF per frame */
  let streamScrollRaf: number | null = null;

  let suggestions: string[] = [];
  let loadingSuggestions = false;
  let suggestionsFetchedFor = ""; // tracks which directory suggestions were fetched for

  // Follow-up suggestions shown below the last AI response
  let followUpSuggestions: string[] = [];
  let followUpLoading = false;

  async function fetchSuggestions() {
    if (loadingSuggestions) return;
    loadingSuggestions = true;
    try {
      const result = await apiService.getSuggestions();
      suggestions = result;
      if (!result.length) suggestionsFetchedFor = ""; // allow retry next cycle
    } catch {
      suggestions = [];
      suggestionsFetchedFor = ""; // allow retry
    } finally {
      loadingSuggestions = false;
    }
  }

  // Wait until content indexing is done before fetching — avoids racing the
  // indexing pipeline and triggering a second fetch that clears existing results.
  $: if (
    $metadataIndexed &&
    !$contentIndexingInProgress &&
    !loadingSuggestions &&
    $systemStatus?.current_directory &&
    $systemStatus.current_directory !== suggestionsFetchedFor
  ) {
    suggestionsFetchedFor = $systemStatus.current_directory;
    fetchSuggestions();
  }

  function getScrollTopToAlignElementTop(container: HTMLElement, el: HTMLElement): number {
    const elRect = el.getBoundingClientRect();
    const cRect = container.getBoundingClientRect();
    return container.scrollTop + (elRect.top - cRect.top);
  }

  /** Scroll so the anchor’s top edge sits at the top of the messages viewport (with small padding). */
  function scrollLastAiResponseToTop(smooth: boolean) {
    if (!messagesContainer || !shouldAutoScroll) return;
    tick().then(() => {
      if (!messagesContainer) return;
      const el = document.getElementById(CHAT_SCROLL_ANCHOR_ID);
      if (!el) {
        const { scrollHeight, clientHeight } = messagesContainer;
        messagesContainer.scrollTo({
          top: Math.max(0, scrollHeight - clientHeight),
          behavior: smooth ? "smooth" : "auto",
        });
        return;
      }
      const pad = 8;
      const nextTop = Math.max(0, getScrollTopToAlignElementTop(messagesContainer, el) - pad);
      messagesContainer.scrollTo({
        top: nextTop,
        behavior: smooth ? "smooth" : "auto",
      });
    });
  }

  function scheduleScrollDuringStream() {
    if (!shouldAutoScroll) return;
    if (streamScrollRaf != null) return;
    streamScrollRaf = requestAnimationFrame(() => {
      streamScrollRaf = null;
      scrollLastAiResponseToTop(false);
    });
  }

  function handleScroll() {
    if (!messagesContainer) return;
    const { scrollTop, scrollHeight, clientHeight } = messagesContainer;
    const anchor = document.getElementById(CHAT_SCROLL_ANCHOR_ID);
    const atBottom = scrollTop + clientHeight >= scrollHeight - 60;
    if (!anchor) {
      shouldAutoScroll = atBottom;
      return;
    }
    const goal = Math.max(0, getScrollTopToAlignElementTop(messagesContainer, anchor) - 8);
    const nearFollow = Math.abs(scrollTop - goal) < 140;
    shouldAutoScroll = nearFollow || atBottom;
  }

  onMount(() => {
    // Load messages if session exists
    if ($currentChatSession) {
      loadSession($currentChatSession);
    }
    
    // Listen for session load events from layout
    window.addEventListener('loadSession', handleSessionLoad as EventListener);

    setTimeout(() => scrollLastAiResponseToTop(false), 200);

    return () => {
      window.removeEventListener('loadSession', handleSessionLoad as EventListener);
      if (streamScrollRaf != null) {
        cancelAnimationFrame(streamScrollRaf);
        streamScrollRaf = null;
      }
    };
  });

  function handleSessionLoad(event: CustomEvent) {
    loadSession(event.detail);
  }

  async function loadSession(session: any) {
    try {
      currentChatSession.set(session);
      const response = await apiService.getChatMessages(session.id);
      const sessionMessages = response.messages || [];
      if (Array.isArray(sessionMessages)) {
        messages = sessionMessages;
      } else {
        messages = [];
      }
      setTimeout(() => scrollLastAiResponseToTop(false), 200);
    } catch (error) {
      console.error("❌ Failed to load session:", error);
      messages = [];
    }
  }

  async function handleSendMessage(event: CustomEvent<{ message: string }>) {
    await sendMessage(event.detail.message);
  }

  async function sendMessage(message: string) {
    if (!message.trim()) return;

    // Allow queries once metadata is indexed (even if content is still indexing)
    // Only block if metadata isn't indexed yet
    if (!$metadataIndexed) {
      return;
    }

    // Clear follow-up suggestions from the previous exchange
    followUpSuggestions = [];
    followUpLoading = false;

    // Create or get current chat session
    let session = $currentChatSession;
    if (!session) {
      session = await apiService.createChatSession(
        $systemStatus?.current_directory || "",
        messageToConversationTitle(message),
      );
      currentChatSession.set(session);
      await loadChatHistory();
    }

    // Add user message to UI immediately
    const userMessage: ChatMessage = {
      id: Date.now(),
      session_id: session.id,
      user_message: message,
      ai_response: "",
      sources: [],
      response_time: 0,
      timestamp: new Date().toISOString(),
    };

    messages = [...messages, userMessage];
    setTimeout(() => scrollLastAiResponseToTop(true), 50);
    apiActions.setChatLoading(true);

    try {
      await apiService.sendChatMessageStream(
        { session_id: session.id, message },
        {
          onMeta(sources) {
            messages = messages.map((msg) =>
              msg.id === userMessage.id ? { ...msg, sources } : msg,
            );
            setTimeout(() => scrollLastAiResponseToTop(true), 50);
          },
          onEditProposal(proposal) {
            messages = messages.map((msg) =>
              msg.id === userMessage.id ? { ...msg, edit_proposal: proposal } : msg,
            );
          },
          onToken(delta) {
            messages = messages.map((msg) =>
              msg.id === userMessage.id
                ? { ...msg, ai_response: msg.ai_response + delta }
                : msg,
            );
            scheduleScrollDuringStream();
          },
          onDone(finalMessage, responseTime) {
            messages = messages.map((msg) =>
              msg.id === userMessage.id
                ? { ...msg, ai_response: finalMessage, response_time: responseTime }
                : msg,
            );
            setTimeout(() => scrollLastAiResponseToTop(true), 80);
            // Fetch follow-up suggestions asynchronously — don't block the response
            followUpLoading = true;
            apiService.getFollowUpSuggestions(message, finalMessage).then((s) => {
              followUpSuggestions = s;
              followUpLoading = false;
            });
          },
          onError(detail) {
            throw new Error(detail || "Stream failed");
          },
        },
      );

      const updated = messages.find((m) => m.id === userMessage.id);
      if (
        updated?.ai_response &&
        updated.ai_response.includes("couldn't generate a response due to an error")
      ) {
        throw new Error("AI service temporarily unavailable. Please try again.");
      }

      if (messages.length === 2) {
        const newTitle = messageToConversationTitle(message);
        await apiService.updateChatSessionTitle(session.id, newTitle);
        session.title = newTitle;
        currentChatSession.set(session);
      }

      await loadChatHistory();
    } catch (error) {
      console.error("❌ Failed to send message:", error);
      const errorMessage: ChatMessage = {
        id: Date.now(),
        session_id: session.id,
        user_message: message,
        ai_response: `❌ Error: ${error instanceof Error ? error.message : "Unknown error"}`,
        sources: [],
        response_time: 0,
        timestamp: new Date().toISOString(),
      };
      messages = messages.map((msg) =>
        msg.id === userMessage.id ? errorMessage : msg,
      );
    } finally {
      apiActions.setChatLoading(false);
    }
  }

  async function loadChatHistory() {
    try {
      const sessions = await apiService.getChatSessions();
      chatHistory.set(sessions);
    } catch (error) {
      console.error("❌ Failed to load chat history:", error);
    }
  }

  function startNewChat() {
    currentChatSession.set(null);
    messages = [];
  }

  // Watch for session changes
  $: if (!$currentChatSession && messages.length > 0) {
    messages = [];
    }
  </script>
  
  <svelte:head>
  <title>Klair AI - Chat Interface</title>
  </svelte:head>

<!-- Main Chat Area -->
<div class="relative flex-1 flex flex-col bg-white dark:bg-gray-950 min-h-0">
  <!--
    Watermark: fixed to viewport so negative offsets don’t grow scroll height (see layout overflow-x-hidden).
    Scale: compact on mobile → sm/md bridge → lg (desktop hero). Opacity: raise numbers = less transparent / stronger.
  -->
  <div
    class="pointer-events-none fixed z-[1] select-none
      bottom-[-2.25rem] right-[-2.25rem] w-[min(20rem,88vw)] h-[min(20rem,72vh)]
      sm:bottom-[-3.5rem] sm:right-[-3.5rem] sm:w-[min(36rem,94vw)] sm:h-[min(36rem,86vh)]
      md:bottom-[-8rem] md:right-[-6rem] md:w-[min(48rem,98vw)] md:h-[min(48rem,90vh)]
      lg:bottom-[-18rem] lg:right-[-12rem] lg:w-[min(64rem,100vw)] lg:h-[min(64rem,96vh)]"
    aria-hidden="true"
  >
    <img
      src="/klair.ai-sm.png"
      alt=""
      class="h-full w-full object-contain [object-position:bottom_right]"
      style="opacity: {$theme === 'dark' ? WATERMARK_OPACITY.dark : WATERMARK_OPACITY.light}"
    />
  </div>

  {#if $currentChatSession}
    <!-- Session Header -->
    <div class="relative z-10 bg-white dark:bg-gray-950 px-8 py-6 flex-shrink-0">
      <div class="flex items-center justify-between">
        <div class="flex-1 min-w-0">
          <h2 class="text-xl font-semibold text-[#37352F] dark:text-gray-100 truncate">
            {$currentChatSession.title}
          </h2>
          <div class="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Created {formatCalendarDate($currentChatSession.created_at)}
          </div>
        </div>
      </div>
    </div>
  {:else}
    <div class="relative z-10 bg-white dark:bg-gray-950 px-8 py-6 flex-shrink-0">
      <h2 class="text-lg font-semibold text-[#37352F] dark:text-gray-100">New Chat</h2>
      <p class="text-gray-600 dark:text-gray-400 text-sm">
        Start a new conversation about your documents
      </p>
        </div>
      {/if}
  
  <!-- Messages Container -->
  <div 
    bind:this={messagesContainer}
    class="relative z-10 flex-1 overflow-y-auto p-8 space-y-6"
    onscroll={handleScroll}
  >
    {#if messages.length === 0}
      <div class="flex flex-col items-center mt-16 px-4">
        <h3 class="text-4xl font-bold tracking-tight text-[#37352F] dark:text-gray-100 mb-3 text-center">
          Welcome to Klair AI!
        </h3>
        <p class="text-gray-600 dark:text-gray-400 text-xs mb-8 text-center">
          Start a conversation by asking questions about your documents.
        </p>

        {#if $metadataIndexed}
          {#if loadingSuggestions}
            <!-- Skeleton chips while generating -->
            <div class="flex flex-wrap justify-center gap-3 max-w-xl">
              {#each [1, 2, 3, 4] as _}
                <div class="h-9 w-48 rounded-full bg-gray-100 dark:bg-gray-800 animate-pulse"></div>
              {/each}
            </div>
          {:else if suggestions.length > 0}
            <div class="flex flex-wrap justify-center gap-3 max-w-2xl">
              {#each suggestions as suggestion}
                <button
                  type="button"
                  onclick={() => sendMessage(suggestion)}
                  class="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-[#443C68]/25 dark:border-[#8B7FC4]/30 bg-white dark:bg-gray-900 text-sm text-[#37352F] dark:text-gray-200 hover:border-[#443C68] dark:hover:border-[#8B7FC4] hover:bg-[#443C68]/5 dark:hover:bg-[#443C68]/15 transition-all shadow-sm hover:shadow-md"
                >
                  <svg class="w-3.5 h-3.5 text-[#443C68] dark:text-[#8B7FC4] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-3 3v-3z" />
                  </svg>
                  <span>{suggestion}</span>
                </button>
              {/each}
            </div>
          {/if}
        {/if}
      </div>
    {:else}
      {#each messages as message, i}
        <!-- User Message -->
        {#if message.user_message}
          <div class="flex justify-end">
            <div class="max-w-2xl">
              <!-- User Label -->
              <div class="flex items-center justify-end gap-2 mb-2">
                <span class="text-xs font-medium text-gray-500">You</span>
                <div class="w-6 h-6 bg-[#443C68] rounded-full flex items-center justify-center">
                  <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                  </svg>
                </div>
              </div>
              <div
                class="bg-[#443C68] text-white px-6 py-4 rounded-2xl rounded-br-md shadow-sm"
              >
                <div class="whitespace-pre-wrap text-sm leading-relaxed">
                  {message.user_message}
                </div>
              </div>
              <div class="text-xs text-gray-400 dark:text-gray-500 mt-2 text-right">
                {new Date(message.timestamp).toLocaleTimeString()}
              </div>
            </div>
        </div>
      {/if}
  
        <!-- AI Response (trim avoids empty bubble vs loading anchor duplicate id) -->
        {#if String(message.ai_response || "").trim()}
          <div
            class="flex justify-start"
            id={i === messages.length - 1 ? CHAT_SCROLL_ANCHOR_ID : undefined}
          >
            <div class="max-w-2xl">
              <!-- AI Label -->
              <div class="flex items-center gap-2 mb-2">
                <div class="w-6 h-6 bg-[#443C68] rounded-full flex items-center justify-center">
                  <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                  </svg>
                </div>
                <span class="text-xs font-medium text-gray-500 dark:text-gray-400">Klair</span>
              </div>
              <div
                class="bg-[#F7F7F7] dark:bg-gray-900 text-[#37352F] dark:text-gray-100 px-6 py-4 rounded-2xl rounded-bl-md shadow-sm"
              >
                <MarkdownRenderer content={message.ai_response} className="text-sm leading-relaxed" />
              </div>

              <!-- Edit Proposal Card -->
              {#if message.edit_proposal}
                <EditProposalCard
                  proposal={message.edit_proposal}
                  onApplied={() => {
                    messages = messages.map((m) =>
                      m.id === message.id ? { ...m, edit_proposal: null } : m
                    );
                  }}
                  onDiscarded={() => {
                    messages = messages.map((m) =>
                      m.id === message.id ? { ...m, edit_proposal: null } : m
                    );
                  }}
                />
              {/if}

              <!-- Message Metadata -->
              

              <!-- Sources Display -->
              {#if message.sources && message.sources.length > 0}
                {@const isExpanded = expandedSources[message.id] ?? false}
                {@const previewLimit = 3}
                {@const hasMoreSources = message.sources.length > previewLimit}
                {@const displayedSources = isExpanded ? message.sources : message.sources.slice(0, previewLimit)}
                
                <div
                  class="mt-3 p-4 bg-[#443C68]/5 dark:bg-[#443C68]/10 dark:ring-1 dark:ring-[#443C68]/25 rounded-xl"
                >
                  <!-- Header - only interactive if there are more than 3 sources -->
                  {#if hasMoreSources}
                    <button
                      onclick={() => {
                        expandedSources[message.id] = !isExpanded;
                        expandedSources = { ...expandedSources };
                      }}
                      class="w-full text-sm font-semibold text-[#443C68] dark:text-[#C9C2EB] mb-3 flex items-center justify-between hover:text-[#3A3457] dark:hover:text-white transition-colors"
                    >
                      <div class="flex text-xs items-center gap-2 text-[#443C68] dark:text-[#C9C2EB]">
                        <svg
                          class="w-4 h-4 shrink-0"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                          ></path>
                        </svg>
                        <span>Sources ({message.sources.length})</span>
                      </div>
                      <svg
                        class="w-4 h-4 transition-transform {isExpanded ? 'rotate-180' : ''}"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                      </svg>
                    </button>
                  {:else}
                    <div class="text-sm font-semibold text-[#443C68] dark:text-[#C9C2EB] mb-3 flex items-center gap-2">
                      <svg
                        class="w-4 h-4 shrink-0"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          stroke-width="2"
                          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                        ></path>
                      </svg>
                      <span>Sources ({message.sources.length})</span>
                    </div>
                  {/if}
                  
                  <!-- Sources list -->
                  {#if hasMoreSources && isExpanded}
                    <!-- Expanded: Vertical cards with full details -->
                    <div class="space-y-3">
                      {#each displayedSources as source}
                        <button
                          type="button"
                          class="w-full text-left flex items-start gap-3 p-3 bg-white dark:bg-gray-950 rounded-lg border border-gray-100 dark:border-gray-800 hover:border-[#443C68]/40 dark:hover:border-[#8B7FC4]/40 hover:bg-[#443C68]/5 transition-colors cursor-pointer"
                          title="Open {source.file_path?.split('\\').pop()}{source.page_number ? ` · p.${source.page_number}` : ''} in document viewer"
                          onclick={() => window.dispatchEvent(new CustomEvent('openDocumentViewer', {
                            detail: { filePath: source.file_path, searchText: source.content_snippet ?? '', pageNumber: source.page_number ?? null }
                          }))}
                        >
                          <div
                            class="w-8 h-8 bg-gray-100 rounded-lg flex items-center justify-center flex-shrink-0"
                          >
                            <FileTypeIcon fileType={source.file_type} class="w-4 h-4 flex-shrink-0" />
                            <span class="sr-only">{getFileTypeConfig(source.file_type).label}</span>
                          </div>
                          <div class="flex-1 min-w-0">
                            <div
                              class="text-sm font-medium text-[#37352F] dark:text-gray-100 truncate mb-1"
                            >
                              {source.file_path?.split("\\").pop() ||
                                "Unknown file"}
                            </div>
                            <div class="text-xs text-gray-600 mb-2">
                              Relevance: {(
                                source.relevance_score * 100
                              ).toFixed(1)}%
                            </div>
                            <div class="text-xs text-gray-500 line-clamp-2">
                              {source.content_snippet || "No content preview"}
                            </div>
                          </div>
                        </button>
                      {/each}
                    </div>
                  {:else}
                    <!-- Collapsed or ≤3 sources: Horizontal chips (minimal space) -->
                    <div class="flex flex-wrap gap-2">
                      {#each displayedSources as source}
                        <button
                          type="button"
                          class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-950 rounded-full border border-gray-200 dark:border-gray-700 text-[0.625rem] text-gray-700 dark:text-gray-200 hover:border-[#443C68] dark:hover:border-[#8B7FC4] hover:bg-[#443C68]/5 transition-colors cursor-pointer"
                          title="Open {source.file_path?.split('\\').pop()}{source.page_number ? ` · p.${source.page_number}` : ''} — {(source.relevance_score * 100).toFixed(1)}% relevance"
                          onclick={() => window.dispatchEvent(new CustomEvent('openDocumentViewer', {
                            detail: { filePath: source.file_path, searchText: source.content_snippet ?? '', pageNumber: source.page_number ?? null }
                          }))}
                        >
                          <FileTypeIcon fileType={source.file_type} class="w-3.5 h-3.5 flex-shrink-0" />
                          <span class="font-bold {getFileTypeConfig(source.file_type).color} uppercase">
                            {getFileTypeConfig(source.file_type).label}
                          </span>
                          <span class="text-[#37352F] dark:text-gray-200 font-medium truncate max-w-[200px]">
                            {source.file_path?.split("\\").pop() || "Unknown"}
                          </span>
                          <span class="text-gray-500 dark:text-gray-400 tabular-nums">
                            {(source.relevance_score * 100).toFixed(0)}%
                          </span>
                        </button>
                      {/each}
                      
                        <!-- Show more button as inline chip -->
                        {#if hasMoreSources && !isExpanded}
                          <button
                            onclick={() => {
                              expandedSources[message.id] = true;
                              expandedSources = { ...expandedSources };
                            }}
                            class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#443C68] text-white rounded-full border border-[#443C68] dark:border-[#5A4F8A] text-[0.625rem] hover:bg-[#3A3457] dark:hover:bg-[#52477A] transition-colors font-medium"
                          >
                            + {message.sources.length - previewLimit} more
                          </button>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/if}
                <div
                class="flex items-center gap-4 mt-3 text-xs text-gray-500 dark:text-gray-400"
              >
                <span
                  >{new Date(message.timestamp).toLocaleTimeString()}</span
                >
                {#if message.response_time}
                  <span
                    class="bg-[#443C68]/10 text-[#443C68] px-2 py-1 rounded-full"
                  >
                    {message.response_time}s
                  </span>
                {/if}
              </div>

              <!-- Follow-up suggestions — only on the last completed message -->
              {#if i === messages.length - 1 && !$isChatLoading}
                {#if followUpLoading}
                  <div class="flex gap-2 mt-3">
                    {#each [1, 2, 3] as _}
                      <div class="h-7 w-32 rounded-full bg-gray-200 dark:bg-gray-700 animate-pulse"></div>
                    {/each}
                  </div>
                {:else if followUpSuggestions.length > 0}
                  <div class="flex flex-wrap gap-2 mt-3">
                    {#each followUpSuggestions as s}
                      <button
                        type="button"
                        onclick={() => sendMessage(s)}
                        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full
                          border border-[#443C68]/30 dark:border-[#443C68]/40
                          text-[#443C68] dark:text-purple-300
                          bg-[#443C68]/5 dark:bg-[#443C68]/10
                          hover:bg-[#443C68]/15 dark:hover:bg-[#443C68]/20
                          hover:border-[#443C68]/60
                          transition-all active:scale-95"
                      >
                        <svg class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                        {s}
                      </button>
                    {/each}
                  </div>
                {/if}
              {/if}

              </div>
            </div>
          {/if}
        {/each}

        <!-- Loading indicator: anchor before first streamed token (avoids duplicate id with AI bubble) -->
        {#if $isChatLoading && messages.length > 0 && !String(messages[messages.length - 1]?.ai_response || "").trim()}
          <div class="flex justify-start" id={CHAT_SCROLL_ANCHOR_ID}>
            <div class="max-w-2xl">
              <!-- AI Label -->
              <div class="flex items-center gap-2 mb-2">
                <div class="w-6 h-6 bg-[#443C68] rounded-full flex items-center justify-center">
                  <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                  </svg>
                </div>
                <span class="text-xs font-medium text-gray-500 dark:text-gray-400">AI Assistant</span>
              </div>
              <div
                class="bg-[#F7F7F7] dark:bg-gray-900 text-[#37352F] dark:text-gray-100 px-6 py-4 rounded-2xl rounded-bl-md shadow-sm"
              >
                <div class="flex items-center gap-2">
                  <div
                    class="w-2 h-2 bg-[#443C68] rounded-full animate-bounce"
                  ></div>
                  <div
                    class="w-2 h-2 bg-[#443C68] rounded-full animate-bounce"
                    style="animation-delay: 0.1s"
                  ></div>
                  <div
                    class="w-2 h-2 bg-[#443C68] rounded-full animate-bounce"
                    style="animation-delay: 0.2s"
                  ></div>
                </div>
              </div>
            </div>
          </div>
        {/if}
        {/if}
      </div>
  
    <!-- Chat Input (transparent shell so bottom-right watermark stays visible behind controls) -->
    <div class="relative z-10 bg-transparent p-8 flex-shrink-0">
      <div class="max-w-4xl mx-auto">
        {#if !$metadataIndexed}
          <!-- Metadata Indexing Message -->
          <div class="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4">
            <div class="flex items-center gap-3">
              <svg class="animate-spin h-5 w-5 text-blue-600 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <div class="flex-1">
                <p class="text-sm font-medium text-blue-900">
                  Indexing document metadata...
                </p>
                <p class="text-xs text-blue-700 mt-1">
                  This will only take a moment. Chat will be available shortly.
                </p>
              </div>
            </div>
          </div>
        {:else if $contentIndexingInProgress}
          <!-- Content Indexing Message (non-blocking) with progress -->
          <div class="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-4">
            <div class="flex items-center gap-3">
              <svg class="animate-spin h-5 w-5 text-amber-600 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <div class="flex-1">
                <p class="text-sm font-medium text-amber-900">
                  Content indexing in progress…
                  {#if $indexingProgress.total > 0}
                    <span class="font-normal text-amber-800">{$indexingProgress.indexed} of {$indexingProgress.total} documents</span>
                  {/if}
                </p>
                <p class="text-xs text-amber-700 mt-1">
                  You can query files by name now. Full content search will be available once indexing completes.
                </p>
              </div>
            </div>
          </div>
        {/if}
        
        <div class="flex items-center gap-4">
          <div class="flex-1">
            <textarea
              id="chat-input"
              placeholder={!$metadataIndexed ? "Setting up…" : $contentIndexingInProgress ? "Ask about files by name, or wait for content indexing…" : "Ask me anything about your documents…"}
              rows="1"
              disabled={!$metadataIndexed}
              class="text-sm  w-full h-full px-6 py-4 border border-gray-200 dark:border-gray-800 rounded-2xl resize-none focus:outline-none focus:ring-2 focus:ring-[#443C68] focus:border-transparent text-[#37352F] dark:text-gray-100 bg-white dark:bg-gray-950 placeholder-gray-400 dark:placeholder-gray-500 disabled:bg-gray-100 dark:disabled:bg-gray-900 disabled:cursor-not-allowed disabled:opacity-60"
              style="min-height: 56px; max-height: 120px;"
              onkeydown={(e) => {
                if (!$metadataIndexed) {
                  e.preventDefault();
                  return;
                }
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  const input = e.target as HTMLTextAreaElement;
                  if (input && input.value.trim()) {
                    handleSendMessage({
                      detail: { message: input.value.trim() },
                    } as any);
                    input.value = "";
                  }
                }
              }}
            ></textarea>
          </div>
    
          <button
            onclick={() => {
              if (!$metadataIndexed) return;
              const input = document.getElementById(
                "chat-input",
              ) as HTMLTextAreaElement;
              if (input && input.value.trim()) {
                handleSendMessage({
                  detail: { message: input.value.trim() },
                } as any);
                input.value = "";
              }
            }}
            disabled={$isChatLoading || !$metadataIndexed}
            class="px-8 h-[56px] text-sm bg-[#443C68] text-white rounded-2xl hover:bg-[#3A3457] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-3 font-medium flex-shrink-0"
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
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              ></path>
            </svg>
            Send
          </button>
        </div>
  
        <div class="text-xs text-gray-400 dark:text-gray-500 mt-3 text-center">
          {#if !$metadataIndexed}
            Setting up… Chat will be available shortly
          {:else if $contentIndexingInProgress}
            Content indexing in background{#if $indexingProgress.total > 0} ({$indexingProgress.indexed} of {$indexingProgress.total}){/if}. You can query files by name
          {:else}
            Press Enter to send, Shift+Enter for new line
          {/if}
      </div>
      </div>
    </div>
  </div>
