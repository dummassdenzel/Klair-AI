<script lang="ts">
    import { onMount } from 'svelte';
    import { apiService } from '$lib/api/services';
    import { systemStatus, isLoading, error, apiActions } from '$lib/stores/api';
    import { createApiRequest } from '$lib/utils/api';
  
    let directoryPath = 'C:\\xampp\\htdocs\\klair-ai\\documents';
  
    onMount(async () => {
      // Test backend connection on page load
      await testConnection();
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
          // Refresh status after setting directory
          await testConnection();
          return result;
        },
        'Set directory'
      );
    }
  
    async function clearIndex() {
      await createApiRequest(
        async () => {
          const result = await apiService.clearIndex();
          // Refresh status after clearing
          await testConnection();
          return result;
        },
        'Clear index'
      );
    }
  </script>
  
  <svelte:head>
    <title>Klair AI - Backend Connection Test</title>
  </svelte:head>
  
  <main class="min-h-screen bg-gray-50 p-8">
    <div class="max-w-4xl mx-auto">
      <h1 class="text-3xl font-bold text-gray-900 mb-8">�� Backend Connection Test</h1>
      
      <!-- Error Display -->
      {#if $error}
        <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-6">
          <strong>Error:</strong> {$error}
        </div>
      {/if}
  
      <!-- Loading Indicator -->
      {#if $isLoading}
        <div class="bg-blue-100 border border-blue-400 text-blue-700 px-4 py-3 rounded mb-6">
          <strong>Loading...</strong> Please wait...
        </div>
      {/if}
  
      <!-- Connection Status -->
      <div class="bg-white rounded-lg shadow p-6 mb-6">
        <h2 class="text-xl font-semibold mb-4">📡 Connection Status</h2>
        
        {#if $systemStatus}
          <div class="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span class="font-medium">Directory Set:</span>
              <span class="ml-2 {$systemStatus.directory_set ? 'text-green-600' : 'text-red-600'}">
                {$systemStatus.directory_set ? '✅ Yes' : '❌ No'}
              </span>
            </div>
            <div>
              <span class="font-medium">Processor Ready:</span>
              <span class="ml-2 {$systemStatus.processor_ready ? 'text-green-600' : 'text-red-600'}">
                {$systemStatus.processor_ready ? '✅ Yes' : '❌ No'}
              </span>
            </div>
            <div>
              <span class="font-medium">Current Directory:</span>
              <span class="ml-2 text-gray-600">{$systemStatus.current_directory || 'None'}</span>
            </div>
            <div>
              <span class="font-medium">Total Documents:</span>
              <span class="ml-2 text-gray-600">{$systemStatus.database_stats?.total_documents || 0}</span>
            </div>
          </div>
        {:else}
          <p class="text-gray-500">No status information available</p>
        {/if}
      </div>
  
      <!-- Directory Management -->
      <div class="bg-white rounded-lg shadow p-6 mb-6">
        <h2 class="text-xl font-semibold mb-4">📁 Directory Management</h2>
        
        <div class="flex gap-4 mb-4">
          <input
            type="text"
            bind:value={directoryPath}
            placeholder="Enter directory path"
            class="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            on:click={setDirectory}
            disabled={$isLoading}
            class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Set Directory
          </button>
        </div>
  
        <button
          on:click={clearIndex}
          disabled={$isLoading}
          class="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Clear Index
        </button>
      </div>
  
      <!-- Test Connection Button -->
      <div class="bg-white rounded-lg shadow p-6">
        <h2 class="text-xl font-semibold mb-4">�� Test Connection</h2>
        <button
          on:click={testConnection}
          disabled={$isLoading}
          class="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Test Backend Connection
        </button>
      </div>
    </div>
  </main>