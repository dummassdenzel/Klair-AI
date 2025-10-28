<script lang="ts">
  import { onMount } from "svelte";
  import { apiService } from "$lib/api/services";
  import {
    systemStatus,
    currentChatSession,
    chatHistory,
    isChatLoading,
    apiActions,
  } from "$lib/stores/api";
  import { createApiRequest } from "$lib/utils/api";
  import type { ChatRequest, ChatMessage } from "$lib/api/types";

  let messages: ChatMessage[] = [];
  let directoryPath = "C:\\xampp\\htdocs\\klair-ai\\documents";
  
    onMount(async () => {
    console.log(" Component mounted, testing connection...");
      await testConnection();
    console.log(" Connection tested, loading chat history...");
    await loadChatHistory();
    console.log("🔍 Initialization complete");
    });
  
    async function testConnection() {
    console.log(" Testing connection...");
    await createApiRequest(async () => {
          const status = await apiService.getStatus();
      console.log("🔍 Status:", status);
          systemStatus.set(status);
          return status;
    }, "Backend connection test");
    }
  
    async function setDirectory() {
    console.log("🔍 Setting directory...");
      if (!directoryPath.trim()) return;
      
    await createApiRequest(async () => {
          const result = await apiService.setDirectory(directoryPath);
      console.log("🔍 Directory set:", result);
          await testConnection();
          return result;
    }, "Set directory");
  }

  async function loadChatHistory() {
    console.log("🔍 Loading chat history...");
    try {
      const sessions = await apiService.getChatSessions();
      console.log("🔍 Chat sessions loaded:", sessions);
      chatHistory.set(sessions);
    } catch (error) {
      console.error("❌ Failed to load chat history:", error);
    }
  }

  async function handleSendMessage(event: CustomEvent<{ message: string }>) {
    console.log("🔍 handleSendMessage called with:", event.detail);
    const { message } = event.detail;

    if (!message.trim()) return;

    console.log("🔍 Creating/checking chat session...");

    // Create or get current chat session
    let session = $currentChatSession;
    if (!session) {
      console.log("🔍 No existing session, creating new one...");
      session = await apiService.createChatSession(
        $systemStatus?.current_directory || "",
        `Chat about: ${message.substring(0, 50)}...`,
      );
      console.log("🔍 New session created:", session);
      currentChatSession.set(session);
      await loadChatHistory();
    }

    console.log("🔍 Adding user message to UI...");

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
    console.log("🔍 Messages updated:", messages);

    // Set loading state
    apiActions.setChatLoading(true);

    try {
      console.log(" Sending message to backend...");
      const response = await apiService.sendChatMessage({
        session_id: session.id,
        message: message,
      });
      console.log("🔍 Backend response:", response);

      // Check if the AI response is an error message
      if (
        response.message &&
        response.message.includes(
          "couldn't generate a response due to an error",
        )
      ) {
        console.warn("⚠️ AI returned error response, treating as failure");
        throw new Error(
          "AI service temporarily unavailable. Please try again.",
        );
      }

      // Update the user message with AI response
      const updatedMessage: ChatMessage = {
        ...userMessage,
        ai_response: response.message,
        sources: response.sources,
        response_time: response.response_time,
      };

      messages = messages.map((msg) =>
        msg.id === userMessage.id ? updatedMessage : msg,
      );

      // Update session title if it's the first message
      if (messages.length === 2) {
        // User message + AI response
        const newTitle = `Chat about: ${message.substring(0, 50)}...`;
        await apiService.updateChatSessionTitle(session.id, newTitle);
        session.title = newTitle;
        currentChatSession.set(session);
        await loadChatHistory();
      }
    } catch (error) {
      console.error("❌ Failed to send message:", error);

      // Show user-friendly error message
      const errorMessage: ChatMessage = {
        id: Date.now(),
        session_id: session.id,
        user_message: message,
        ai_response: `❌ Error: ${error instanceof Error ? error.message : "Unknown error"}`,
        sources: [],
        response_time: 0,
        timestamp: new Date().toISOString(),
      };

      // Replace the user message with error message
      messages = messages.map((msg) =>
        msg.id === userMessage.id ? errorMessage : msg,
      );
    } finally {
      apiActions.setChatLoading(false);
    }
  }

  async function handleUpdateTitle(event: CustomEvent<{ title: string }>) {
    if (!$currentChatSession) return;

    await createApiRequest(async () => {
      const updatedSession = await apiService.updateChatSessionTitle(
        $currentChatSession.id,
        event.detail.title,
      );
      currentChatSession.set(updatedSession);
      await loadChatHistory();
      return updatedSession;
    }, "Update session title");
  }

  async function handleDeleteSession() {
    if (!$currentChatSession) return;

    await createApiRequest(async () => {
      await apiService.deleteChatSession($currentChatSession.id);
      currentChatSession.set(null);
      messages = [];
      await loadChatHistory();
      return true;
    }, "Delete session");
  }

  async function startNewChat() {
    console.log("🔍 Starting new chat...");
    currentChatSession.set(null);
    messages = [];
  }

  async function loadSession(session: any) {
    console.log(" Loading session:", session);
    try {
      currentChatSession.set(session);
      console.log("🔍 Current session set, loading messages...");

      const response = await apiService.getChatMessages(session.id);
      console.log("🔍 Raw API response:", response);

      // Extract messages from nested response structure
      const sessionMessages = response.messages || [];
      console.log(" Extracted messages:", sessionMessages);
      console.log("🔍 Messages count:", sessionMessages.length);

      // Validate and filter messages before updating UI
      if (Array.isArray(sessionMessages)) {
        console.log(" Messages is array, updating UI...");
        messages = sessionMessages;
        console.log(
          "🔍 Messages updated successfully, count:",
          messages.length,
        );
      } else {
        console.error("❌ Messages is not an array:", sessionMessages);
        messages = [];
      }
    } catch (error) {
      console.error("❌ Failed to load session:", error);
      messages = [];
    }
    }
  </script>
  
  <svelte:head>
  <title>Klair AI - Chat Interface</title>
  <link
    href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap"
    rel="stylesheet"
  />
  </svelte:head>
  
<div class="min-h-screen bg-white font-['Inter']">
  <!-- Top Navigation -->
  <div class="bg-white border-b border-gray-100 px-6 py-4">
    <div class="flex items-center justify-between">
      <!-- Logo and Title -->
      <div class="flex items-center gap-3">
        <div class="flex items-center space-x-2">
          <img src="/klair.ai-sm.png" class="w-7 h-7" alt="User avatar" />
          <span class="font-bold text-xl">klair.ai</span>
        </div>
      </div>

      <!-- Directory Status and Controls -->
      <div class="flex items-center gap-6">
        <div class="text-sm text-[#37352F] bg-[#F7F7F7] px-4 py-2 rounded-lg">
          {#if $systemStatus?.directory_set}
            📁 {$systemStatus.current_directory?.split("\\").pop()}
          {:else}
            📁 No directory set
      {/if}
        </div>

        <button
          on:click={setDirectory}
          class="px-6 py-2.5 bg-[#443C68] text-white rounded-lg hover:bg-[#3A3457] transition-colors font-medium"
        >
          Set Directory
        </button>
      </div>
    </div>
  </div>

  <div class="flex h-[calc(100vh-120px)]">
    <!-- Left Sidebar - Chat History -->
    <div class="w-80 bg-[#F7F7F7] border-r border-gray-100 flex flex-col">
      <!-- New Chat Button -->
      <div class="p-6 border-b border-gray-100">
        <button
          on:click={startNewChat}
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

      <!-- Chat History -->
      <div class="flex-1 overflow-y-auto p-6">
        <h3
          class="text-sm font-semibold text-[#37352F] mb-4 uppercase tracking-wide"
        >
          Recent Chats
        </h3>
        <div class="space-y-3">
          {#each $chatHistory as session}
            <button
              on:click={() => loadSession(session)}
              class="w-full text-left p-4 rounded-xl hover:bg-white transition-all duration-200 {$currentChatSession?.id ===
              session.id
                ? 'bg-white shadow-sm border border-[#443C68]/20'
                : ''}"
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
          {/each}
        </div>
      </div>
    </div>

    <!-- Main Chat Area -->
    <div class="flex-1 flex flex-col bg-white">
      {#if $currentChatSession}
        <!-- Session Header -->
        <div class="bg-white border-b border-gray-100 px-8 py-6">
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

            <button
              on:click={handleDeleteSession}
              class="p-3 text-red-500 hover:text-red-600 hover:bg-red-50 rounded-xl transition-colors"
              title="Delete session"
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
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                ></path>
              </svg>
            </button>
          </div>
        </div>
      {:else}
        <div class="bg-white border-b border-gray-100 px-8 py-6">
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
            <div class="  flex items-center justify-center mx-auto mb-6">
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
                  <div
                    class="bg-[#F7F7F7] text-[#37352F] px-6 py-4 rounded-2xl rounded-bl-md shadow-sm"
                  >
                    <div class="whitespace-pre-wrap text-sm leading-relaxed">
                      {message.ai_response}
                    </div>
                  </div>

                  <!-- Message Metadata -->
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

                  <!-- Sources Display -->
                  {#if message.sources && message.sources.length > 0}
                    <div
                      class="mt-4 p-4 bg-[#443C68]/5 rounded-xl border border-[#443C68]/20"
                    >
                      <div
                        class="text-sm font-semibold text-[#443C68] mb-3 flex items-center gap-2"
                      >
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
                        Sources ({message.sources.length})
                      </div>
                      <div class="space-y-3">
                        {#each message.sources as source}
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
                    </div>
                  {/if}
                </div>
              </div>
            {/if}
          {/each}

          <!-- Loading indicator for new message -->
          {#if $isChatLoading}
            <div class="flex justify-start">
              <div class="max-w-2xl">
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
      <div class="border-t border-gray-100 bg-white p-8">
        <div class="max-w-4xl mx-auto">
          <div class="flex items-end gap-4">
            <div class="flex-1">
              <textarea
                id="chat-input"
                placeholder="Ask me anything about your documents..."
                rows="1"
                class="w-full px-6 py-4 border border-gray-200 rounded-2xl resize-none focus:outline-none focus:ring-2 focus:ring-[#443C68] focus:border-transparent text-[#37352F] placeholder-gray-400"
                style="min-height: 56px; max-height: 120px;"
              />
        </div>
  
        <button
              on:click={() => {
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
              disabled={$isChatLoading}
              class="px-8 py-4 bg-[#443C68] text-white rounded-2xl hover:bg-[#3A3457] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-3 font-medium"
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
            Press Enter to send, Shift+Enter for new line
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
