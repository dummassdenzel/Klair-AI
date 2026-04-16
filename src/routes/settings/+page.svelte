<script lang="ts">
  import { onMount } from 'svelte';
  import { theme, applyTheme, type Theme } from '$lib/stores/theme';
  import { apiService } from '$lib/api/services';
  import type { LLMProvider, LLMConfig, LLMConfigUpdate } from '$lib/api/types';

  // ── Theme ────────────────────────────────────────────────────────────────
  function setTheme(next: Theme) {
    applyTheme(next);
  }

  // ── LLM provider state ───────────────────────────────────────────────────
  type SaveState = 'idle' | 'saving' | 'success' | 'error';

  let loading = $state(true);
  let saveState = $state<SaveState>('idle');
  let errorMessage = $state('');

  let selectedProvider = $state<LLMProvider>('ollama');

  // Ollama
  let ollamaBaseUrl = $state('http://localhost:11434');
  let ollamaModel = $state('tinyllama');

  // Gemini
  let geminiModel = $state('gemini-2.5-pro');
  let geminiApiKey = $state('');
  let geminiApiKeySet = $state(false);

  // Groq
  let groqModel = $state('meta-llama/llama-4-scout-17b-16e-instruct');
  let groqApiKey = $state('');
  let groqApiKeySet = $state(false);

  // Generation temperature (shared across all providers)
  let temperature = $state(0.1);

  const PROVIDER_LABELS: Record<LLMProvider, string> = {
    ollama: 'Ollama',
    gemini: 'Gemini',
    groq: 'Groq',
  };

  const PROVIDER_DESCRIPTIONS: Record<LLMProvider, string> = {
    ollama: 'Local inference — no API key required.',
    gemini: 'Google Gemini cloud API.',
    groq: 'Groq cloud API — fast inference.',
  };

  async function loadConfig() {
    try {
      const cfg: LLMConfig = await apiService.getLLMConfig();
      selectedProvider = cfg.provider;
      temperature = cfg.temperature ?? 0.1;
      ollamaBaseUrl = cfg.ollama_base_url;
      ollamaModel = cfg.ollama_model;
      geminiModel = cfg.gemini_model;
      geminiApiKeySet = cfg.gemini_api_key_set;
      groqModel = cfg.groq_model;
      groqApiKeySet = cfg.groq_api_key_set;
    } catch {
      // backend may not be running yet — silently ignore
    } finally {
      loading = false;
    }
  }

  async function saveConfig() {
    saveState = 'saving';
    errorMessage = '';

    const update: LLMConfigUpdate = { provider: selectedProvider, temperature };

    if (selectedProvider === 'ollama') {
      update.ollama_model = ollamaModel.trim() || undefined;
      update.ollama_base_url = ollamaBaseUrl.trim() || undefined;
    } else if (selectedProvider === 'gemini') {
      update.gemini_model = geminiModel.trim() || undefined;
      if (geminiApiKey.trim()) update.gemini_api_key = geminiApiKey.trim();
    } else if (selectedProvider === 'groq') {
      update.groq_model = groqModel.trim() || undefined;
      if (groqApiKey.trim()) update.groq_api_key = groqApiKey.trim();
    }

    try {
      const result = await apiService.updateLLMConfig(update);
      // Sync key-set flags and temperature from response
      geminiApiKeySet = result.gemini_api_key_set;
      groqApiKeySet = result.groq_api_key_set;
      if (result.temperature != null) temperature = result.temperature;
      // Clear plaintext key inputs after a successful save
      geminiApiKey = '';
      groqApiKey = '';
      saveState = 'success';
      setTimeout(() => { saveState = 'idle'; }, 2500);
    } catch (e: any) {
      errorMessage = e?.response?.data?.detail ?? e?.message ?? 'Failed to save configuration.';
      saveState = 'error';
    }
  }

  onMount(loadConfig);
</script>

<svelte:head>
  <title>Klair AI - Settings</title>
</svelte:head>

<div class="flex-1 bg-white dark:bg-gray-950 min-h-0">
  <div class="max-w-4xl mx-auto px-8 py-10">
    <div class="mb-8">
      <h1 class="text-2xl font-semibold text-[#37352F] dark:text-gray-100">Settings</h1>
      <p class="text-sm text-gray-600 dark:text-gray-400 mt-2">
        Customize your experience.
      </p>
    </div>

    <div class="space-y-4">

      <!-- ── Appearance ────────────────────────────────────────────────── -->
      <div class="bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-2xl p-6 shadow-sm">
        <div class="flex items-start justify-between gap-6">
          <div class="flex-1">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl bg-[#443C68]/10 flex items-center justify-center">
                <svg class="w-5 h-5 text-[#443C68]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m8-9h1M3 12H2m15.364-6.364l.707.707M5.929 18.071l-.707.707m12.142 0l-.707-.707M6.636 6.636l-.707-.707M12 18a6 6 0 100-12 6 6 0 000 12z" />
                </svg>
              </div>
              <div>
                <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">Appearance</h2>
                <p class="text-xs text-gray-600 dark:text-gray-400 mt-1">Choose a theme for the app.</p>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-2 bg-gray-100 dark:bg-gray-900 p-1 rounded-xl border border-gray-200 dark:border-gray-800">
            <button
              type="button"
              onclick={() => setTheme('light')}
              class="px-4 py-2 text-xs rounded-lg transition-colors font-medium
                {$theme === 'light'
                  ? 'bg-white dark:bg-gray-950 text-[#37352F] dark:text-gray-100 shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-[#37352F] dark:hover:text-white'}"
              aria-pressed={$theme === 'light'}
            >Light</button>
            <button
              type="button"
              onclick={() => setTheme('dark')}
              class="px-4 py-2 text-xs rounded-lg transition-colors font-medium
                {$theme === 'dark'
                  ? 'bg-white dark:bg-gray-950 text-[#37352F] dark:text-gray-100 shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-[#37352F] dark:hover:text-white'}"
              aria-pressed={$theme === 'dark'}
            >Dark</button>
          </div>
        </div>
      </div>

      <!-- ── AI Model ──────────────────────────────────────────────────── -->
      <div class="bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-2xl p-6 shadow-sm">
        <div class="flex items-center gap-3 mb-6">
          <div class="w-10 h-10 rounded-xl bg-[#443C68]/10 flex items-center justify-center">
            <svg class="w-5 h-5 text-[#443C68]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.346a4 4 0 00-.999 1.354l-.142.49a2 2 0 01-1.93 1.474H10.88a2 2 0 01-1.93-1.474l-.141-.49a4 4 0 00-1-1.354l-.346-.346z" />
            </svg>
          </div>
          <div class="flex-1">
            <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">AI Model</h2>
            <p class="text-xs text-gray-600 dark:text-gray-400 mt-1">Choose your LLM provider and model.</p>
          </div>

          {#if !loading}
            <!-- Active-provider badge -->
            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium
              bg-[#443C68]/10 text-[#443C68] dark:bg-[#443C68]/20 dark:text-purple-300">
              <span class="w-1.5 h-1.5 rounded-full bg-[#443C68] dark:bg-purple-400"></span>
              {PROVIDER_LABELS[selectedProvider]} active
            </span>
          {/if}
        </div>

        {#if loading}
          <div class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 py-4">
            <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
            </svg>
            Loading configuration…
          </div>
        {:else}
          <!-- Provider selector tabs -->
          <div class="flex gap-2 mb-6">
            {#each (['ollama', 'gemini', 'groq'] as LLMProvider[]) as p}
              <button
                type="button"
                onclick={() => { selectedProvider = p; saveState = 'idle'; }}
                class="flex-1 py-2.5 px-3 rounded-xl text-xs font-medium border transition-all
                  {selectedProvider === p
                    ? 'bg-[#443C68] text-white border-[#443C68] shadow-sm'
                    : 'bg-gray-50 dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-800 hover:border-[#443C68]/50 hover:text-[#443C68] dark:hover:text-purple-300'}"
              >
                {PROVIDER_LABELS[p]}
              </button>
            {/each}
          </div>

          <p class="text-xs text-gray-500 dark:text-gray-400 mb-5">
            {PROVIDER_DESCRIPTIONS[selectedProvider]}
          </p>

          <!-- Provider-specific fields -->
          {#if selectedProvider === 'ollama'}
            <div class="space-y-4">
              <div>
                <label for="ollama-url" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Base URL
                </label>
                <input
                  id="ollama-url"
                  type="text"
                  bind:value={ollamaBaseUrl}
                  placeholder="http://localhost:11434"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                    placeholder-gray-400 dark:placeholder-gray-600
                    focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                    transition-colors"
                />
              </div>
              <div>
                <label for="ollama-model" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Model name
                </label>
                <input
                  id="ollama-model"
                  type="text"
                  bind:value={ollamaModel}
                  placeholder="tinyllama"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                    placeholder-gray-400 dark:placeholder-gray-600
                    focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                    transition-colors"
                />
              </div>
            </div>

          {:else if selectedProvider === 'gemini'}
            <div class="space-y-4">
              <div>
                <label for="gemini-model" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Model name
                </label>
                <input
                  id="gemini-model"
                  type="text"
                  bind:value={geminiModel}
                  placeholder="gemini-2.5-pro"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                    placeholder-gray-400 dark:placeholder-gray-600
                    focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                    transition-colors"
                />
              </div>
              <div>
                <label for="gemini-key" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  API Key
                  {#if geminiApiKeySet}
                    <span class="ml-1 text-green-600 dark:text-green-400 font-normal">(configured)</span>
                  {/if}
                </label>
                <input
                  id="gemini-key"
                  type="password"
                  bind:value={geminiApiKey}
                  placeholder={geminiApiKeySet ? 'Leave blank to keep existing key' : 'Enter your Gemini API key'}
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                    placeholder-gray-400 dark:placeholder-gray-600
                    focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                    transition-colors"
                />
              </div>
            </div>

          {:else if selectedProvider === 'groq'}
            <div class="space-y-4">
              <div>
                <label for="groq-model" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Model name
                </label>
                <input
                  id="groq-model"
                  type="text"
                  bind:value={groqModel}
                  placeholder="meta-llama/llama-4-scout-17b-16e-instruct"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                    placeholder-gray-400 dark:placeholder-gray-600
                    focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                    transition-colors"
                />
              </div>
              <div>
                <label for="groq-key" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  API Key
                  {#if groqApiKeySet}
                    <span class="ml-1 text-green-600 dark:text-green-400 font-normal">(configured)</span>
                  {/if}
                </label>
                <input
                  id="groq-key"
                  type="password"
                  bind:value={groqApiKey}
                  placeholder={groqApiKeySet ? 'Leave blank to keep existing key' : 'Enter your Groq API key'}
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                    placeholder-gray-400 dark:placeholder-gray-600
                    focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                    transition-colors"
                />
              </div>
            </div>
          {/if}

          <!-- Temperature control -->
          <div class="mt-6 pt-5 border-t border-gray-100 dark:border-gray-800">
            <div class="flex items-center justify-between mb-2">
              <div>
                <label for="llm-temperature" class="block text-xs font-medium text-gray-700 dark:text-gray-300">
                  Response Temperature
                </label>
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  Controls answer randomness. Lower = more consistent and factual.
                </p>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-xs font-mono font-semibold text-[#443C68] dark:text-purple-300 w-8 text-right">
                  {temperature.toFixed(2)}
                </span>
                {#if temperature <= 0.2}
                  <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                    Recommended
                  </span>
                {/if}
              </div>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-xs text-gray-400 dark:text-gray-500 shrink-0">Precise</span>
              <input
                id="llm-temperature"
                type="range"
                min="0"
                max="1"
                step="0.05"
                bind:value={temperature}
                class="flex-1 h-2 rounded-full appearance-none cursor-pointer
                  accent-[#443C68]
                  bg-gray-200 dark:bg-gray-700"
              />
              <span class="text-xs text-gray-400 dark:text-gray-500 shrink-0">Creative</span>
            </div>
          </div>

          <!-- Save row -->
          <div class="flex items-center justify-between mt-5">
            {#if saveState === 'success'}
              <span class="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                Saved successfully
              </span>
            {:else if saveState === 'error'}
              <span class="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
                {errorMessage}
              </span>
            {:else}
              <span></span>
            {/if}

            <button
              type="button"
              onclick={saveConfig}
              disabled={saveState === 'saving'}
              class="inline-flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-semibold
                bg-[#443C68] text-white hover:bg-[#362f55] active:scale-95
                disabled:opacity-60 disabled:cursor-not-allowed
                transition-all shadow-sm"
            >
              {#if saveState === 'saving'}
                <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
                </svg>
                Saving…
              {:else}
                Save
              {/if}
            </button>
          </div>
        {/if}
      </div>

      <!-- ── About ──────────────────────────────────────────────────────── -->
      <div class="bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-2xl p-6 shadow-sm">
        <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">About</h2>
        <p class="text-xs text-gray-600 dark:text-gray-400 mt-2">
          Klair AI — folder-scoped RAG assistant. Settings will expand here over time.
        </p>
      </div>

    </div>
  </div>
</div>
