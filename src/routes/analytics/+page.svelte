<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { apiService } from '$lib/api/services';

  let queryPatterns: any = null;
  let documentUsage: any = null;
  let retrievalEffectiveness: any = null;
  let performanceTrends: any = null;
  let querySuccess: any = null;
  let loading = true;
  let error: string | null = null;
  let refreshInterval: any = null;
  let timeWindow = 60; // minutes

  // Type definition for success stats
  type SuccessStats = {
    success_rate: number;
    total: number;
    success: number;
    failed: number;
  };

  async function loadAnalytics() {
    try {
      loading = true;
      error = null;

      // Load all analytics in parallel
      const [
        patternsRes,
        usageRes,
        effectivenessRes,
        trendsRes,
        successRes
      ] = await Promise.all([
        apiService.getQueryPatterns(timeWindow),
        apiService.getDocumentUsage(),
        apiService.getRetrievalEffectiveness(timeWindow),
        apiService.getPerformanceTrends(timeWindow, 6),
        apiService.getQuerySuccess(timeWindow)
      ]);

      queryPatterns = patternsRes.patterns || patternsRes.data?.patterns;
      documentUsage = usageRes.usage || usageRes.data?.usage;
      retrievalEffectiveness = effectivenessRes.effectiveness || effectivenessRes.data?.effectiveness;
      performanceTrends = trendsRes.trends || trendsRes.data?.trends;
      querySuccess = successRes.success || successRes.data?.success;
    } catch (e: any) {
      error = e.message || 'Failed to load analytics';
      console.error('Error loading analytics:', e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadAnalytics();
    // Auto-refresh every 30 seconds
    refreshInterval = setInterval(loadAnalytics, 30000);
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

  function getTrendIcon(trend: string): string {
    switch (trend) {
      case 'increasing':
        return '↗️';
      case 'decreasing':
        return '↘️';
      default:
        return '→';
    }
  }

  function getTrendColor(trend: string): string {
    switch (trend) {
      case 'increasing':
        return 'text-red-600';
      case 'decreasing':
        return 'text-green-600';
      default:
        return 'text-gray-600';
    }
  }
</script>

<div class="rag-analytics-dashboard p-6 bg-white min-h-screen">
  <div class="m-10">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold text-gray-900">RAG Analytics</h1>
        <p class="text-gray-600 mt-1">Query patterns, document usage, and retrieval insights</p>
      </div>
      <div class="flex items-center gap-4">
        <select
          bind:value={timeWindow}
          on:change={loadAnalytics}
          class="px-3 py-2 border border-gray-300 rounded-lg text-sm"
        >
          <option value={15}>Last 15 minutes</option>
          <option value={60}>Last hour</option>
          <option value={360}>Last 6 hours</option>
          <option value={1440}>Last 24 hours</option>
        </select>
        <button
          on:click={loadAnalytics}
          disabled={loading}
          class="px-4 py-2 bg-[#443C68] text-white rounded-lg hover:bg-[#3A3457] disabled:opacity-50 text-sm"
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

    {#if loading && !queryPatterns}
      <div class="text-center py-12">
        <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-[#443C68]"></div>
        <p class="mt-2 text-gray-600">Loading analytics...</p>
      </div>
    {:else if queryPatterns}
      <!-- Query Patterns Section -->
      <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
        <h2 class="text-xl font-semibold text-gray-900 mb-4">Query Patterns</h2>
        
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <!-- Common Keywords -->
          {#if queryPatterns.common_keywords && queryPatterns.common_keywords.length > 0}
            <div>
              <h3 class="text-sm font-medium text-gray-700 mb-3">Top Keywords</h3>
              <div class="flex flex-wrap gap-2">
                {#each queryPatterns.common_keywords.slice(0, 15) as item}
                  <div class="px-3 py-1 bg-[#443C68] text-white rounded-full text-sm font-medium">
                    {item.keyword} ({item.count})
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          <!-- Query Types -->
          {#if queryPatterns.query_patterns && Object.keys(queryPatterns.query_patterns).length > 0}
            <div>
              <h3 class="text-sm font-medium text-gray-700 mb-3">Question Patterns</h3>
              <div class="space-y-2">
                {#each Object.entries(queryPatterns.query_patterns) as [pattern, count]}
                  <div class="flex items-center justify-between p-2 bg-gray-50 rounded-lg">
                    <span class="text-sm text-gray-700 capitalize">{pattern.replace('_', ' ')}</span>
                    <span class="font-semibold text-gray-900">{count}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>

        <!-- Query Length Stats -->
        {#if queryPatterns.query_length_stats}
          <div class="mt-6 pt-6 border-t border-gray-200">
            <h3 class="text-sm font-medium text-gray-700 mb-3">Query Length Statistics</h3>
            <div class="grid grid-cols-4 gap-4">
              <div>
                <p class="text-xs text-gray-500">Average</p>
                <p class="text-lg font-semibold">{queryPatterns.query_length_stats.average?.toFixed(1) || 0} chars</p>
              </div>
              <div>
                <p class="text-xs text-gray-500">Median</p>
                <p class="text-lg font-semibold">{queryPatterns.query_length_stats.median || 0} chars</p>
              </div>
              <div>
                <p class="text-xs text-gray-500">Min</p>
                <p class="text-lg font-semibold">{queryPatterns.query_length_stats.min || 0} chars</p>
              </div>
              <div>
                <p class="text-xs text-gray-500">Max</p>
                <p class="text-lg font-semibold">{queryPatterns.query_length_stats.max || 0} chars</p>
              </div>
            </div>
          </div>
        {/if}

        <!-- Peak Hours -->
        {#if queryPatterns.peak_hours && Object.keys(queryPatterns.peak_hours).length > 0}
          <div class="mt-6 pt-6 border-t border-gray-200">
            <h3 class="text-sm font-medium text-gray-700 mb-3">Peak Query Hours</h3>
            <div class="flex flex-wrap gap-3">
              {#each Object.entries(queryPatterns.peak_hours).slice(0, 5) as [hour, count]}
                <div class="px-4 py-2 bg-[#443C68] rounded-lg">
                  <span class="text-sm text-white font-medium">{hour}:00</span>
                  <span class="ml-2 text-sm font-semibold text-white">{count} queries</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>

      <!-- Retrieval Effectiveness -->
      {#if retrievalEffectiveness}
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
          <h2 class="text-xl font-semibold text-gray-900 mb-4">Retrieval Effectiveness</h2>
          
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="p-4 bg-[#443C68] rounded-lg">
              <p class="text-sm text-white/80 mb-1">Avg Retrieval Count</p>
              <p class="text-2xl font-bold text-white">
                {retrievalEffectiveness.average_retrieval_count?.toFixed(1) || 0}
              </p>
              <p class="text-xs text-white/60 mt-1">chunks per query</p>
            </div>
            
            <div class="p-4 bg-[#443C68] rounded-lg">
              <p class="text-sm text-white/80 mb-1">Avg Sources</p>
              <p class="text-2xl font-bold text-white">
                {retrievalEffectiveness.average_sources_count?.toFixed(1) || 0}
              </p>
              <p class="text-xs text-white/60 mt-1">sources shown</p>
            </div>
            
            <div class="p-4 bg-[#443C68] rounded-lg">
              <p class="text-sm text-white/80 mb-1">Re-rank Usage</p>
              <p class="text-2xl font-bold text-white">
                {formatPercent(retrievalEffectiveness.rerank_usage_rate || 0)}
              </p>
              <p class="text-xs text-white/60 mt-1">of queries</p>
            </div>
          </div>

          {#if retrievalEffectiveness.retrieval_to_sources_ratio}
            <div class="mt-4 pt-4 border-t border-gray-200">
              <p class="text-sm text-gray-600 mb-2">Retrieval Efficiency</p>
              <div class="flex items-center gap-2">
                <div class="flex-1 bg-gray-200 rounded-full h-2">
                  <div
                    class="bg-[#443C68] h-2 rounded-full"
                    style="width: {Math.min(retrievalEffectiveness.retrieval_to_sources_ratio, 100)}%"
                  ></div>
                </div>
                <span class="text-sm font-semibold text-gray-700">
                  {retrievalEffectiveness.retrieval_to_sources_ratio.toFixed(1)}%
                </span>
              </div>
              <p class="text-xs text-gray-500 mt-1">Percentage of retrieved chunks that become sources</p>
            </div>
          {/if}
        </div>
      {/if}

      <!-- Performance Trends -->
      {#if performanceTrends && performanceTrends.time_buckets}
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
          <h2 class="text-xl font-semibold text-gray-900 mb-4">Performance Trends</h2>
          
          <div class="flex items-center gap-6 mb-4">
            <div>
              <p class="text-xs text-gray-500">Response Time Trend</p>
              <p class="text-lg font-semibold {getTrendColor(performanceTrends.response_time_trend)}">
                {getTrendIcon(performanceTrends.response_time_trend)} {performanceTrends.response_time_trend}
              </p>
            </div>
            <div>
              <p class="text-xs text-gray-500">Error Rate Trend</p>
              <p class="text-lg font-semibold {getTrendColor(performanceTrends.error_rate_trend)}">
                {getTrendIcon(performanceTrends.error_rate_trend)} {performanceTrends.error_rate_trend}
              </p>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
              <thead class="bg-gray-50">
                <tr>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time Bucket</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Queries</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Avg Response</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Error Rate</th>
                </tr>
              </thead>
              <tbody class="bg-white divide-y divide-gray-200">
                {#each performanceTrends.time_buckets as bucket}
                  <tr class="hover:bg-gray-50">
                    <td class="px-4 py-3 text-sm text-gray-600">Bucket {bucket.bucket + 1}</td>
                    <td class="px-4 py-3 text-sm text-gray-900">{bucket.query_count}</td>
                    <td class="px-4 py-3 text-sm text-gray-600">
                      {formatTime(bucket.average_response_time_ms)}
                    </td>
                    <td class="px-4 py-3 text-sm">
                      <span class="{bucket.error_rate > 5 ? 'text-red-600' : 'text-gray-600'}">
                        {formatPercent(bucket.error_rate)}
                      </span>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      {/if}

      <!-- Query Success Analysis -->
      {#if querySuccess}
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
          <h2 class="text-xl font-semibold text-gray-900 mb-4">Query Success Analysis</h2>
          
          <div class="mb-6">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium text-gray-700">Overall Success Rate</span>
              <span class="text-lg font-bold text-green-600">
                {formatPercent(querySuccess.success_rate || 0)}
              </span>
            </div>
            <div class="flex-1 bg-gray-200 rounded-full h-3">
              <div
                class="bg-green-600 h-3 rounded-full"
                style="width: {querySuccess.success_rate || 0}%"
              ></div>
            </div>
          </div>

          {#if querySuccess.success_by_type && Object.keys(querySuccess.success_by_type).length > 0}
            <div>
              <h3 class="text-sm font-medium text-gray-700 mb-3">Success Rate by Query Type</h3>
              <div class="space-y-3">
                {#each Object.entries(querySuccess.success_by_type) as [type, stats]}
                  {@const typedStats = stats as SuccessStats}
                  <div>
                    <div class="flex items-center justify-between mb-1">
                      <span class="text-sm text-gray-700 capitalize">{type}</span>
                      <span class="text-sm font-semibold {typedStats.success_rate >= 95 ? 'text-green-600' : typedStats.success_rate >= 80 ? 'text-yellow-600' : 'text-red-600'}">
                        {formatPercent(typedStats.success_rate)}
                      </span>
                    </div>
                    <div class="flex-1 bg-gray-200 rounded-full h-2">
                      <div
                        class="{typedStats.success_rate >= 95 ? 'bg-green-600' : typedStats.success_rate >= 80 ? 'bg-yellow-600' : 'bg-red-600'} h-2 rounded-full"
                        style="width: {typedStats.success_rate}%"
                      ></div>
                    </div>
                    <div class="flex items-center gap-4 mt-1 text-xs text-gray-500">
                      <span>Total: {typedStats.total}</span>
                      <span>Success: {typedStats.success}</span>
                      <span>Failed: {typedStats.failed}</span>
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          {#if querySuccess.common_failure_patterns && querySuccess.common_failure_patterns.length > 0}
            <div class="mt-6 pt-6 border-t border-gray-200">
              <h3 class="text-sm font-medium text-gray-700 mb-3">Common Failure Patterns</h3>
              <div class="flex flex-wrap gap-2">
                {#each querySuccess.common_failure_patterns as pattern}
                  <div class="px-3 py-1 bg-red-50 text-red-700 rounded-full text-sm">
                    {pattern.keyword} ({pattern.count})
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {/if}

      <!-- Document Usage -->
      {#if documentUsage}
        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
          <h2 class="text-xl font-semibold text-gray-900 mb-4">Document Usage</h2>
          
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="p-4 bg-[#443C68] rounded-lg">
              <p class="text-sm text-white/80 mb-1">Document Queries</p>
              <p class="text-2xl font-bold text-white">
                {documentUsage.total_document_queries || 0}
              </p>
            </div>
            
            <div class="p-4 bg-[#443C68] rounded-lg">
              <p class="text-sm text-white/80 mb-1">Unique Sessions</p>
              <p class="text-2xl font-bold text-white">
                {documentUsage.unique_sessions_using_documents || 0}
              </p>
            </div>
            
            <div class="p-4 bg-[#443C68] rounded-lg">
              <p class="text-sm text-white/80 mb-1">Avg Response Time</p>
              <p class="text-2xl font-bold text-white">
                {formatTime(documentUsage.average_response_time_for_document_queries || 0)}
              </p>
            </div>
          </div>
        </div>
      {/if}
    {:else}
      <div class="text-center py-12 bg-white rounded-xl border border-gray-200">
        <p class="text-gray-600">No analytics data available for the selected time window.</p>
        <p class="text-sm text-gray-500 mt-2">Try making some queries to see analytics here.</p>
      </div>
    {/if}
  </div>
</div>

<style>
  .rag-analytics-dashboard {
    font-family: system-ui, -apple-system, sans-serif;
  }
</style>

