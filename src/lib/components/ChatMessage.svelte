<script lang="ts">
    import type { DocumentSource } from '$lib/api/types';
    
    export let message: string;
    export let isUser: boolean;
    export let timestamp: Date;
    export let sources: DocumentSource[] = [];
    export let responseTime: number = 0; // FIX: Remove the ? and set default value
    export let isLoading: boolean = false;

    // ADD SAFETY CHECKS
    $: safeMessage = message || '';
    $: safeTimestamp = timestamp instanceof Date ? timestamp : new Date();
    $: safeSources = Array.isArray(sources) ? sources : [];
    $: safeResponseTime = typeof responseTime === 'number' ? responseTime : 0;

    $: messageClass = isUser 
      ? 'bg-blue-600 text-white ml-auto' 
      : 'bg-gray-100 text-gray-900 mr-auto';
    
    $: containerClass = `flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`;
  </script>
  
  <div class={containerClass}>
    <div class="max-w-3xl">
      <!-- Message Bubble -->
      <div class="flex items-start gap-3">
        {#if !isUser}
          <div class="w-8 h-8 bg-gray-300 rounded-full flex items-center justify-center flex-shrink-0 mt-1">
            <span class="text-sm font-medium text-gray-600">AI</span>
          </div>
        {/if}
        
        <div class="flex-1">
          <div class="rounded-lg px-4 py-3 {messageClass}">
            {#if isLoading}
              <div class="flex items-center gap-2">
                <div class="w-2 h-2 bg-current rounded-full animate-bounce"></div>
                <div class="w-2 h-2 bg-current rounded-full animate-bounce" style="animation-delay: 0.1s"></div>
                <div class="w-2 h-2 bg-current rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
              </div>
            {:else}
              <div class="whitespace-pre-wrap">{safeMessage}</div>
            {/if}
          </div>
          
          <!-- Message Metadata -->
          <div class="flex items-center gap-4 mt-2 text-xs text-gray-500">
            <span>{safeTimestamp.toLocaleTimeString()}</span>
            {#if !isUser && safeResponseTime > 0}
              <span>Response time: {safeResponseTime}s</span>
            {/if}
          </div>
          
          <!-- Sources Display -->
          {#if !isUser && safeSources.length > 0}
            <div class="mt-3 p-3 bg-blue-50 rounded-lg border border-blue-200">
              <div class="text-sm font-medium text-blue-900 mb-2">
                📚 Sources ({safeSources.length})
              </div>
              <div class="space-y-2">
                {#each safeSources as source}
                  <div class="flex items-start gap-2 p-2 bg-white rounded border">
                    <div class="flex-1 min-w-0">
                      <div class="text-sm font-medium text-gray-900 truncate">
                        {source.file_path?.split('\\').pop() || 'Unknown file'}
                      </div>
                      <div class="text-xs text-gray-600">
                        Relevance: {source.relevance_score ? (source.relevance_score * 100).toFixed(1) : 'N/A'}%
                      </div>
                      <div class="text-xs text-gray-500 mt-1 line-clamp-2">
                        {source.content_snippet || 'No content preview'}
                      </div>
                    </div>
                    <div class="text-xs text-gray-400">
                      {source.file_type?.toUpperCase() || 'UNKNOWN'}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
        
        {#if isUser}
          <div class="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center flex-shrink-0 mt-1">
            <span class="text-sm font-medium text-white">You</span>
          </div>
        {/if}
      </div>
    </div>
  </div>