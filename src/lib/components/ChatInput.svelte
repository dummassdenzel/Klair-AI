<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    
    export let disabled: boolean = false;
    export let placeholder: string = "Ask me anything about your documents...";
    
    const dispatch = createEventDispatcher<{
      send: { message: string };
    }>();
    
    let message = '';
    let isComposing = false;
    
    function handleSubmit() {
      if (message.trim() && !disabled) {
        dispatch('send', { message: message.trim() });
        message = '';
      }
    }
    
    function handleKeydown(event: KeyboardEvent) {
      if (event.key === 'Enter' && !event.shiftKey && !isComposing) {
        event.preventDefault();
        handleSubmit();
      }
    }
  </script>
  
  <div class="border-t border-gray-200 bg-white p-4">
    <div class="flex items-end gap-3">
      <div class="flex-1">
        <textarea
          bind:value={message}
          on:keydown={handleKeydown}
          on:compositionstart={() => isComposing = true}
          on:compositionend={() => isComposing = false}
          {placeholder}
          {disabled}
          rows="1"
          class="w-full px-4 py-3 border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
          style="min-height: 48px; max-height: 120px;"
        />
      </div>
      
      <button
        on:click={handleSubmit}
        disabled={disabled || !message.trim()}
        class="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path>
        </svg>
        Send
      </button>
    </div>
    
    <div class="text-xs text-gray-500 mt-2">
      Press Enter to send, Shift+Enter for new line
    </div>
  </div>