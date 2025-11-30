<script lang="ts">
  import { onMount } from "svelte";
  import { apiService } from "$lib/api/services";
  import {
    systemStatus,
    currentChatSession,
    chatHistory,
    isChatLoading,
    apiActions,
    isIndexingInProgress,
    metadataIndexed,
    contentIndexingInProgress,
  } from "$lib/stores/api";
  import type { ChatMessage } from "$lib/api/types";

  let messages: ChatMessage[] = [];
  let expandedSources: Record<number, boolean> = {};

  onMount(() => {
    // Load messages if session exists
    if ($currentChatSession) {
      loadSession($currentChatSession);
    }
    
    // Listen for session load events from layout
    window.addEventListener('loadSession', handleSessionLoad as EventListener);
    
    return () => {
      window.removeEventListener('loadSession', handleSessionLoad as EventListener);
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
    } catch (error) {
      console.error("❌ Failed to load session:", error);
      messages = [];
    }
  }

  async function handleSendMessage(event: CustomEvent<{ message: string }>) {
    const { message } = event.detail;
    if (!message.trim()) return;

    // Allow queries once metadata is indexed (even if content is still indexing)
    // Only block if metadata isn't indexed yet
    if (!$metadataIndexed) {
      return;
    }

    // Create or get current chat session
    let session = $currentChatSession;
    if (!session) {
      session = await apiService.createChatSession(
        $systemStatus?.current_directory || "",
        `Chat about: ${message.substring(0, 50)}...`,
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
    apiActions.setChatLoading(true);

    try {
      const response = await apiService.sendChatMessage({
        session_id: session.id,
        message: message,
      });

      if (
        response.message &&
        response.message.includes(
          "couldn't generate a response due to an error",
        )
      ) {
        throw new Error(
          "AI service temporarily unavailable. Please try again.",
        );
      }

      const updatedMessage: ChatMessage = {
        ...userMessage,
        ai_response: response.message,
        sources: response.sources,
        response_time: response.response_time,
      };

      messages = messages.map((msg) =>
        msg.id === userMessage.id ? updatedMessage : msg,
      );

      if (messages.length === 2) {
        const newTitle = `Chat about: ${message.substring(0, 50)}...`;
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
        onclick={() => {
          // Dispatch event to layout to open modal
          window.dispatchEvent(new CustomEvent('openDirectoryModalFromLayout'));
        }}
        class="px-6 py-2.5 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        aria-label="Change document directory"
      >
        Change Directory
      </button>
    {/if}
  </div>
</div>

<!-- Main Chat Area -->
<div class="flex-1 flex flex-col bg-white min-h-0">
  {#if $currentChatSession}
    <!-- Session Header -->
    <div class="bg-white px-8 py-6 flex-shrink-0">
      <div class="flex items-center justify-between">
        <div class="flex-1 min-w-0">
          <h2 class="text-xl font-semibold text-[#37352F] truncate">
            {$currentChatSession.title}
          </h2>
          <div class="text-sm text-gray-500 mt-1">
            Created {new Date(
              $currentChatSession.created_at,
            ).toLocaleDateString()}
          </div>
        </div>
      </div>
    </div>
  {:else}
    <div class="bg-white px-8 py-6 flex-shrink-0">
      <h2 class="text-xl font-semibold text-[#37352F]">New Chat</h2>
      <p class="text-gray-600">
        Start a new conversation about your documents
      </p>
        </div>
      {/if}
  
  <!-- Messages Container -->
  <div class="flex-1 overflow-y-auto p-8 space-y-6">
    {#if messages.length === 0}
      <div class="text-center text-gray-500 mt-20">
        <div class="flex items-center justify-center mx-auto mb-6">
          <img src="/klair.ai-sm.png" class="w-16 h-16" alt="User avatar" />
        </div>
        <h3 class="text-2xl font-semibold text-[#37352F] mb-3">
          Welcome to Klair AI!
        </h3>
        <p class="text-gray-600 text-lg">
          Start a conversation by asking questions about your documents.
        </p>
      </div>
    {:else}
      {#each messages as message}
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
              <div class="text-xs text-gray-400 mt-2 text-right">
                {new Date(message.timestamp).toLocaleTimeString()}
              </div>
            </div>
        </div>
      {/if}
  
        <!-- AI Response -->
        {#if message.ai_response}
          <div class="flex justify-start">
            <div class="max-w-2xl">
              <!-- AI Label -->
              <div class="flex items-center gap-2 mb-2">
                <div class="w-6 h-6 bg-[#443C68] rounded-full flex items-center justify-center">
                  <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                  </svg>
                </div>
                <span class="text-xs font-medium text-gray-500">Klair</span>
              </div>
              <div
                class="bg-[#F7F7F7] text-[#37352F] px-6 py-4 rounded-2xl rounded-bl-md shadow-sm"
              >
                <div class="whitespace-pre-wrap text-sm leading-relaxed">
                  {message.ai_response}
                </div>
              </div>

              <!-- Message Metadata -->
              

              <!-- Sources Display -->
              {#if message.sources && message.sources.length > 0}
                {@const isExpanded = expandedSources[message.id] ?? false}
                {@const previewLimit = 3}
                {@const hasMoreSources = message.sources.length > previewLimit}
                {@const displayedSources = isExpanded ? message.sources : message.sources.slice(0, previewLimit)}
                
                <div
                  class="mt-3 p-4 bg-[#443C68]/5 rounded-xl "
                >
                  <!-- Header - only interactive if there are more than 3 sources -->
                  {#if hasMoreSources}
                    <button
                      onclick={() => {
                        expandedSources[message.id] = !isExpanded;
                        expandedSources = { ...expandedSources };
                      }}
                      class="w-full text-sm font-semibold text-[#443C68] mb-3 flex items-center justify-between hover:text-[#3A3457] transition-colors"
                    >
                      <div class="flex text-xs items-center gap-2">
                        <svg
                          class="w-4 h-4"
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
                    <div class="text-sm font-semibold text-[#443C68] mb-3 flex items-center gap-2">
                      <svg
                        class="w-4 h-4"
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
                        <div
                          class="flex items-start gap-3 p-3 bg-white rounded-lg border border-gray-100"
                        >
                          <div
                            class="w-8 h-8 bg-[#443C68]/10 rounded-lg flex items-center justify-center flex-shrink-0"
                          >
                            <span
                              class="text-xs font-bold text-[#443C68] uppercase"
                            >
                              {source.file_type || "DOC"}
              </span>
            </div>
                          <div class="flex-1 min-w-0">
                            <div
                              class="text-sm font-medium text-[#37352F] truncate mb-1"
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
                        </div>
                      {/each}
                    </div>
                  {:else}
                    <!-- Collapsed or ≤3 sources: Horizontal chips (minimal space) -->
                    <div class="flex flex-wrap gap-2">
                      {#each displayedSources as source}
                        <div
                          class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white rounded-full border border-gray-200 text-[0.625rem] hover:border-[#443C68] transition-colors cursor-default"
                          title="{source.file_path?.split('\\').pop()} - {(source.relevance_score * 100).toFixed(1)}% relevance"
                        >
                          <span class="font-bold text-[#443C68] uppercase">
                            {source.file_type || "DOC"}
                          </span>
                          <span class="text-[#37352F] font-medium truncate max-w-[200px]">
                            {source.file_path?.split("\\").pop() || "Unknown"}
                          </span>
                          <span class="text-gray-500">
                            {(source.relevance_score * 100).toFixed(0)}%
              </span>
            </div>
                      {/each}
                      
                        <!-- Show more button as inline chip -->
                        {#if hasMoreSources && !isExpanded}
                          <button
                            onclick={() => {
                              expandedSources[message.id] = true;
                              expandedSources = { ...expandedSources };
                            }}
                            class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#443C68] text-white rounded-full border border-[#443C68] text-[0.625rem] hover:bg-[#3A3457] transition-colors font-medium"
                          >
                            + {message.sources.length - previewLimit} more
                          </button>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/if}
                <div
                class="flex items-center gap-4 mt-3 text-xs text-gray-500"
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
              </div>
            </div>
          {/if}
        {/each}

        <!-- Loading indicator for new message -->
        {#if $isChatLoading}
          <div class="flex justify-start">
            <div class="max-w-2xl">
              <!-- AI Label -->
              <div class="flex items-center gap-2 mb-2">
                <div class="w-6 h-6 bg-[#443C68] rounded-full flex items-center justify-center">
                  <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                  </svg>
                </div>
                <span class="text-xs font-medium text-gray-500">AI Assistant</span>
              </div>
              <div
                class="bg-[#F7F7F7] text-[#37352F] px-6 py-4 rounded-2xl rounded-bl-md shadow-sm"
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
  
    <!-- Chat Input -->
    <div class="border-t border-gray-100 bg-white p-8 flex-shrink-0">
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
          <!-- Content Indexing Message (non-blocking) -->
          <div class="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-4">
            <div class="flex items-center gap-3">
              <svg class="animate-spin h-5 w-5 text-amber-600 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <div class="flex-1">
                <p class="text-sm font-medium text-amber-900">
                  Content indexing in progress...
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
              placeholder={!$metadataIndexed ? "Indexing metadata..." : $contentIndexingInProgress ? "Ask about files by name, or wait for content indexing..." : "Ask me anything about your documents..."}
              rows="1"
              disabled={!$metadataIndexed}
              class="w-full h-full px-6 py-4 border border-gray-200 rounded-2xl resize-none focus:outline-none focus:ring-2 focus:ring-[#443C68] focus:border-transparent text-[#37352F] placeholder-gray-400 disabled:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
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
            class="px-8 h-[56px] bg-[#443C68] text-white rounded-2xl hover:bg-[#3A3457] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-3 font-medium flex-shrink-0"
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
  
        <div class="text-xs text-gray-400 mt-3 text-center">
          {#if !$metadataIndexed}
            Indexing metadata... Chat will be available shortly
          {:else if $contentIndexingInProgress}
            Content indexing in background... You can query files by name
          {:else}
            Press Enter to send, Shift+Enter for new line
          {/if}
      </div>
      </div>
    </div>
  </div>
