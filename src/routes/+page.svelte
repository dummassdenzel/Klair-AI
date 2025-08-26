<script lang="ts">
    import { onMount } from 'svelte';
    import { apiService } from '$lib/api/services';
    import { 
      systemStatus, 
      currentChatSession, 
      chatHistory, 
      isChatLoading,
      apiActions 
    } from '$lib/stores/api';
    import { createApiRequest } from '$lib/utils/api';
    import ChatHeader from '$lib/components/ChatHeader.svelte';
    import ChatContainer from '$lib/components/ChatContainer.svelte';
    import type { ChatRequest, ChatMessage } from '$lib/api/types';
  
    let messages: ChatMessage[] = [];
    let directoryPath = 'C:\\xampp\\htdocs\\klair-ai\\documents';
  
    onMount(async () => {
      await testConnection();
      await loadChatHistory();
    });
  
    async function testConnection() {
      await createApiRequest(
        async () => {
          const status = await apiService.getStatus();
          systemStatus.set(status);
          return status;
        },
        'Backend connection test'
      );
    }
  
    async function setDirectory() {
      if (!directoryPath.trim()) return;
      
      await createApiRequest(
        async () => {
          const result = await apiService.setDirectory(directoryPath);
          await testConnection();
          return result;
        },
        'Set directory'
      );
    }
  
    async function loadChatHistory() {
      const sessions = await apiService.getChatSessions();
      chatHistory.set(sessions);
    }
  
    async function handleSendMessage(event: CustomEvent<{ message: string }>) {
      const { message } = event.detail;
      
      if (!message.trim()) return;
  
      // Create or get current chat session
      let session = $currentChatSession;
      if (!session) {
        session = await apiService.createChatSession(
          $systemStatus?.current_directory || '',
          `Chat about: ${message.substring(0, 50)}...`
        );
        currentChatSession.set(session);
        await loadChatHistory();
      }
  
      // Add user message to UI immediately
      const userMessage: ChatMessage = {
        id: Date.now(),
        session_id: session.id,
        user_message: message,
        ai_response: '',
        sources: [],
        response_time: 0,
        timestamp: new Date().toISOString()
      };
      
      messages = [...messages, userMessage];
      
      // Set loading state
      apiActions.setChatLoading(true);
      
      try {
        // Send to backend
        const response = await apiService.sendChatMessage({ message });
        
        // Update the user message with AI response
        const updatedMessage: ChatMessage = {
          ...userMessage,
          ai_response: response.message,
          sources: response.sources,
          response_time: response.response_time
        };
        
        messages = messages.map(msg => 
          msg.id === userMessage.id ? updatedMessage : msg
        );
        
        // Update session title if it's the first message
        if (messages.length === 2) { // User message + AI response
          const newTitle = `Chat about: ${message.substring(0, 50)}...`;
          await apiService.updateChatSessionTitle(session.id, newTitle);
          session.title = newTitle;
          currentChatSession.set(session);
          await loadChatHistory();
        }
        
      } catch (error) {
        console.error('Failed to send message:', error);
        // Remove the failed message
        messages = messages.filter(msg => msg.id !== userMessage.id);
      } finally {
        apiActions.setChatLoading(false);
      }
    }
  
    async function handleUpdateTitle(event: CustomEvent<{ title: string }>) {
      if (!$currentChatSession) return;
      
      await createApiRequest(
        async () => {
          const updatedSession = await apiService.updateChatSessionTitle(
            $currentChatSession.id, 
            event.detail.title
          );
          currentChatSession.set(updatedSession);
          await loadChatHistory();
          return updatedSession;
        },
        'Update session title'
      );
    }
  
    async function handleDeleteSession() {
      if (!$currentChatSession) return;
      
      await createApiRequest(
        async () => {
          await apiService.deleteChatSession($currentChatSession.id);
          currentChatSession.set(null);
          messages = [];
          await loadChatHistory();
          return true;
        },
        'Delete session'
      );
    }
  
    async function startNewChat() {
      currentChatSession.set(null);
      messages = [];
    }
  
    async function loadSession(session: any) {
      currentChatSession.set(session);
      const sessionMessages = await apiService.getChatMessages(session.id);
      messages = sessionMessages;
    }
  </script>
  
  <svelte:head>
    <title>Klair AI - Chat Interface</title>
  </svelte:head>
  
  <div class="min-h-screen bg-gray-50">
    <!-- Top Navigation -->
    <div class="bg-white border-b border-gray-200 px-6 py-4">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold text-gray-900">🤖 Klair AI</h1>
        
        <div class="flex items-center gap-4">
          <!-- Directory Status -->
          <div class="text-sm text-gray-600">
            {#if $systemStatus?.directory_set}
              📁 {$systemStatus.current_directory?.split('\\').pop()}
            {:else}
              📁 No directory set
            {/if}
          </div>
          
          <!-- Set Directory Button -->
          <button
            on:click={setDirectory}
            class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            Set Directory
          </button>
        </div>
      </div>
    </div>
  
    <div class="flex h-[calc(100vh-80px)]">
      <!-- Sidebar -->
      <div class="w-80 bg-white border-r border-gray-200 flex flex-col">
        <!-- New Chat Button -->
        <div class="p-4 border-b border-gray-200">
          <button
            on:click={startNewChat}
            class="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center justify-center gap-2"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
            </svg>
            New Chat
          </button>
        </div>
        
        <!-- Chat History -->
        <div class="flex-1 overflow-y-auto p-4">
          <h3 class="text-sm font-medium text-gray-900 mb-3">Recent Chats</h3>
          <div class="space-y-2">
            {#each $chatHistory as session}
              <button
                on:click={() => loadSession(session)}
                class="w-full text-left p-3 rounded-lg hover:bg-gray-100 transition-colors {$currentChatSession?.id === session.id ? 'bg-blue-50 border border-blue-200' : ''}"
              >
                <div class="text-sm font-medium text-gray-900 truncate">
                  {session.title}
                </div>
                <div class="text-xs text-gray-500">
                  {new Date(session.created_at).toLocaleDateString()}
                </div>
              </button>
            {/each}
          </div>
        </div>
      </div>
  
      <!-- Main Chat Area -->
      <div class="flex-1 flex flex-col">
        {#if $currentChatSession}
          <ChatHeader
            session={$currentChatSession}
            on:updateTitle={handleUpdateTitle}
            on:deleteSession={handleDeleteSession}
          />
        {:else}
          <div class="bg-white border-b border-gray-200 px-6 py-4">
            <h2 class="text-xl font-semibold text-gray-900">New Chat</h2>
            <p class="text-gray-600">Start a new conversation about your documents</p>
          </div>
        {/if}
        
        <ChatContainer
          {messages}
          isLoading={$isChatLoading}
          on:send={handleSendMessage}
        />
      </div>
    </div>
  </div>