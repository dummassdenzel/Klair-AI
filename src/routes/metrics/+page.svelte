<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { apiService } from '$lib/api/services';

  let metricsSummary: any = null;
  let retrievalStats: any = null;
  let recentQueries: any[] = [];
  let timeSeries: any[] = [];
  let loading = true;
  let error: string | null = null;
  let refreshInterval: any = null;
  let timeWindow = 60; // minutes

  async function loadMetrics() {
    try {
      loading = true;
      error = null;

      // Load all metrics in parallel
      const [summaryRes, retrievalRes, queriesRes, timeSeriesRes] = await Promise.all([
        apiService.getMetricsSummary(timeWindow),
        apiService.getRetrievalStats(timeWindow),
        apiService.getRecentQueries(10),
        apiService.getTimeSeries('response_time', timeWindow, 5)
      ]);

      metricsSummary = summaryRes.metrics || summaryRes.data?.metrics;
      retrievalStats = retrievalRes.stats || retrievalRes.data?.stats;
      recentQueries = queriesRes.queries || queriesRes.data?.queries || [];
      timeSeries = timeSeriesRes.time_series || timeSeriesRes.data?.time_series || [];
    } catch (e: any) {
      error = e.message || 'Failed to load metrics';
      console.error('Error loading metrics:', e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadMetrics();
    // Auto-refresh every 10 seconds
    refreshInterval = setInterval(loadMetrics, 10000);
  });

  onDestroy(() => {
    if (refreshInterval) {
      clearInterval(refreshInterval);
    }
  });

  function formatTime(ms: number): string {
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  function formatPercent(value: number): string {
    return `${value.toFixed(1)}%`;
  }

  function getQueryTypeColor(type: string): string {
    switch (type) {
      case 'document':
        return 'bg-blue-100 text-blue-800';
      case 'general':
        return 'bg-green-100 text-green-800';
      case 'greeting':
        return 'bg-purple-100 text-purple-800';
      case 'error':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  }
</script>

<div class="metrics-dashboard p-6 bg-white min-h-screen">
  <div class="m-10">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-3xl font-bold text-gray-900">Metrics Dashboard</h1>
      <div class="flex items-center gap-4">
        <select
          bind:value={timeWindow}
          on:change={loadMetrics}
          class="px-3 py-2 border border-gray-300 rounded-lg text-sm"
        >
          <option value={15}>Last 15 minutes</option>
          <option value={60}>Last hour</option>
          <option value={360}>Last 6 hours</option>
          <option value={1440}>Last 24 hours</option>
        </select>
        <button
          on:click={loadMetrics}
          disabled={loading}
          class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>
    </div>

    {#if error}
      <div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
        Error: {error}
      </div>
    {/if}

    {#if loading && !metricsSummary}
      <div class="text-center py-12">
        <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <p class="mt-2 text-gray-600">Loading metrics...</p>
      </div>
    {:else if metricsSummary}
      <!-- Summary Cards -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <!-- Total Queries -->
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium text-gray-600">Total Queries</p>
              <p class="text-3xl font-bold text-gray-900 mt-2">
                {metricsSummary.total_queries || 0}
              </p>
            </div>
            <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
              <svg class="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
          </div>
        </div>

        <!-- Average Response Time -->
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium text-gray-600">Avg Response Time</p>
              <p class="text-3xl font-bold text-gray-900 mt-2">
                {formatTime(metricsSummary.average_response_time_ms || 0)}
              </p>
              <p class="text-xs text-gray-500 mt-1">
                Min: {formatTime(metricsSummary.min_response_time_ms || 0)} • Max: {formatTime(metricsSummary.max_response_time_ms || 0)}
              </p>
            </div>
            <div class="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
              <svg class="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
        </div>

        <!-- Error Rate -->
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium text-gray-600">Error Rate</p>
              <p class="text-3xl font-bold text-gray-900 mt-2">
                {formatPercent(metricsSummary.error_rate || 0)}
              </p>
              <p class="text-xs text-gray-500 mt-1">
                {metricsSummary.error_count || 0} errors
              </p>
            </div>
            <div class="w-12 h-12 bg-red-100 rounded-lg flex items-center justify-center">
              <svg class="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
          </div>
        </div>

        <!-- Avg Sources -->
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium text-gray-600">Avg Sources</p>
              <p class="text-3xl font-bold text-gray-900 mt-2">
                {(metricsSummary.average_sources_count || 0).toFixed(1)}
              </p>
              <p class="text-xs text-gray-500 mt-1">
                Retrieval: {(metricsSummary.average_retrieval_count || 0).toFixed(0)} chunks
              </p>
            </div>
            <div class="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
              <svg class="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
          </div>
        </div>
      </div>

      <!-- Query Types Breakdown -->
      {#if metricsSummary.query_types && Object.keys(metricsSummary.query_types).length > 0}
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
          <h2 class="text-lg font-semibold text-gray-900 mb-4">Query Types</h2>
          <div class="flex flex-wrap gap-3">
            {#each Object.entries(metricsSummary.query_types) as [type, count]}
              <div class="flex items-center gap-2 px-4 py-2 rounded-lg {getQueryTypeColor(type)}">
                <span class="font-semibold capitalize">{type}</span>
                <span class="font-bold">{count}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Recent Queries Table -->
      {#if recentQueries.length > 0}
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
          <h2 class="text-lg font-semibold text-gray-900 mb-4">Recent Queries</h2>
          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
              <thead class="bg-gray-50">
                <tr>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Query</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Type</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Response</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Sources</th>
                </tr>
              </thead>
              <tbody class="bg-white divide-y divide-gray-200">
                {#each recentQueries as query}
                  <tr class="hover:bg-gray-50">
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                      {new Date(query.timestamp).toLocaleTimeString()}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-900 max-w-xs truncate" title={query.query_preview}>
                      {query.query_preview || '-'}
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap">
                      <span class="px-2 py-1 text-xs rounded-full {getQueryTypeColor(query.query_type)}">
                        {query.query_type}
                      </span>
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                      {formatTime(query.response_time_ms)}
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                      {query.sources_count}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      {/if}
    {:else}
      <div class="text-center py-12 bg-white rounded-xl border border-gray-200">
        <p class="text-gray-600">No metrics available for the selected time window.</p>
        <p class="text-sm text-gray-500 mt-2">Try making some queries to see metrics here.</p>
      </div>
    {/if}
  </div>
</div>

<style>
  .metrics-dashboard {
    font-family: system-ui, -apple-system, sans-serif;
  }
</style>

