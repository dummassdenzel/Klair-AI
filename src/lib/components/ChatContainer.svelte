<script lang="ts">
    import { onMount, tick } from 'svelte';
    import ChatMessage from './ChatMessage.svelte';
    import ChatInput from './ChatInput.svelte';
    import type { ChatMessage as ChatMessageType, DocumentSource } from '$lib/api/types';
    
    export let messages: ChatMessageType[] = [];
    export let isLoading: boolean = false;
    
    let messagesContainer: HTMLDivElement;
    let shouldAutoScroll = true;
    
    // Auto-scroll to bottom when new messages arrive
    $: if (messages.length > 0 && shouldAutoScroll) {
      tick().then(() => {
        if (messagesContainer) {
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
      });
    }
    
    // Handle scroll events to determine if we should auto-scroll
    function handleScroll() {
      const { scrollTop, scrollHeight, clientHeight } = messagesContainer;
      const isAtBottom = scrollTop + clientHeight >= scrollHeight - 10;
      shouldAutoScroll = isAtBottom;
    }
    
    onMount(() => {
      if (messagesContainer) {
        messagesContainer.addEventListener('scroll', handleScroll);
      }
      
      return () => {
        if (messagesContainer) {
          messagesContainer.removeEventListener('scroll', handleScroll);
        }
      };
    });
  </script>
  
  <div class="flex flex-col h-full">
    <!-- Messages Container -->
    <div 
      bind:this={messagesContainer}
      class="flex-1 overflow-y-auto p-4 space-y-4"
    >
      {#if messages.length === 0}
        <div class="text-center text-gray-500 mt-20">
          <div class="text-6xl mb-4">🤖</div>
          <h3 class="text-xl font-medium mb-2">Welcome to Klair AI!</h3>
          <p class="text-gray-600">
            Start a conversation by asking questions about your documents.
          </p>
        </div>
      {:else}
        {#each messages as message, index}
          <ChatMessage
            message={message.user_message || message.ai_response}
            isUser={!!message.user_message}
            timestamp={new Date(message.timestamp)}
            sources={message.sources || []}
            responseTime={message.response_time}
          />
        {/each}
        
        <!-- Loading indicator for new message -->
        {#if isLoading}
          <ChatMessage
            message=""
            isUser={false}
            timestamp={new Date()}
            sources={[]}
            isLoading={true}
          />
        {/if}
      {/if}
    </div>
    
    <!-- Input Area -->
    <ChatInput
      disabled={isLoading}
      on:send={({ detail }) => {
        // This will be handled by the parent component
        // We're just dispatching the event up
      }}
    />
  </div>