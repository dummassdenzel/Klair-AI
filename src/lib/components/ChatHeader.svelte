<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import type { ChatSession } from '$lib/api/types';
    
    export let session: ChatSession | null = null;
    export let isEditing: boolean = false;
    
    const dispatch = createEventDispatcher<{
      updateTitle: { title: string };
      deleteSession: void;
    }>();
    
    let editTitle = '';
    let showDeleteConfirm = false;
    
    $: if (session) {
      editTitle = session.title;
    }
    
    function startEditing() {
      isEditing = true;
      editTitle = session?.title || '';
    }
    
    function saveTitle() {
      if (editTitle.trim() && session) {
        dispatch('updateTitle', { title: editTitle.trim() });
        isEditing = false;
      }
    }
    
    function cancelEditing() {
      isEditing = false;
      editTitle = session?.title || '';
    }
    
    function confirmDelete() {
      showDeleteConfirm = true;
    }
    
    function handleDelete() {
      dispatch('deleteSession');
      showDeleteConfirm = false;
    }
  </script>
  
  <div class="bg-white border-b border-gray-200 px-6 py-4">
    <div class="flex items-center justify-between">
      <div class="flex-1 min-w-0">
        {#if isEditing}
          <div class="flex items-center gap-2">
            <input
              bind:value={editTitle}
              class="flex-1 px-3 py-1 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              on:keydown={(e) => e.key === 'Enter' && saveTitle()}
              on:blur={saveTitle}
              autofocus
            />
            <button
              on:click={saveTitle}
              class="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
            >
              Save
            </button>
            <button
              on:click={cancelEditing}
              class="px-3 py-1 bg-gray-300 text-gray-700 text-sm rounded hover:bg-gray-400"
            >
              Cancel
            </button>
          </div>
        {:else}
          <div class="flex items-center gap-3">
            <h1 class="text-xl font-semibold text-gray-900 truncate">
              {session?.title || 'New Chat'}
            </h1>
            <button
              on:click={startEditing}
              class="p-1 text-gray-400 hover:text-gray-600 rounded"
              title="Edit title"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
              </svg>
            </button>
          </div>
          
          {#if session}
            <div class="text-sm text-gray-500 mt-1">
              Created {new Date(session.created_at).toLocaleDateString()}
            </div>
          {/if}
        {/if}
      </div>
      
      {#if session}
        <div class="flex items-center gap-2">
          <button
            on:click={confirmDelete}
            class="p-2 text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors"
            title="Delete session"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
            </svg>
          </button>
        </div>
      {/if}
    </div>
  </div>
  
  <!-- Delete Confirmation Modal -->
  {#if showDeleteConfirm}
    <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-white rounded-lg p-6 max-w-md mx-4">
        <h3 class="text-lg font-medium text-gray-900 mb-4">Delete Chat Session?</h3>
        <p class="text-gray-600 mb-6">
          This action cannot be undone. All messages in this session will be permanently deleted.
        </p>
        <div class="flex gap-3 justify-end">
          <button
            on:click={() => showDeleteConfirm = false}
            class="px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400"
          >
            Cancel
          </button>
          <button
            on:click={handleDelete}
            class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  {/if}