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

  // activeProvider reflects what's actually running (from backend), shown in the badge.
  // selectedProvider is what's currently being edited in the form.
  let activeProvider = $state<LLMProvider>('ollama');
  let activeModel = $state('');
  let selectedProvider = $state<LLMProvider>('ollama');

  // Per-provider model selections
  let ollamaBaseUrl = $state('http://localhost:11434');
  let ollamaModel = $state('tinyllama');
  let geminiModel = $state('gemini-2.5-pro');
  let geminiApiKey = $state('');
  let geminiApiKeySet = $state(false);
  let groqModel = $state('meta-llama/llama-4-scout-17b-16e-instruct');
  let groqApiKey = $state('');
  let groqApiKeySet = $state(false);
  let openaiModel = $state('gpt-4o-mini');
  let openaiApiKey = $state('');
  let openaiApiKeySet = $state(false);
  let anthropicModel = $state('claude-sonnet-4-6');
  let anthropicApiKey = $state('');
  let anthropicApiKeySet = $state(false);
  let xaiModel = $state('grok-3-mini');
  let xaiApiKey = $state('');
  let xaiApiKeySet = $state(false);

  let temperature = $state(0.1);

  const PROVIDER_LABELS: Record<LLMProvider, string> = {
    ollama: 'Ollama (local)',
    gemini: 'Gemini',
    groq: 'Groq',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    xai: 'xAI',
  };

  const MODEL_OPTIONS: Record<LLMProvider, string[]> = {
    ollama: ['tinyllama', 'llama3.2', 'llama3.1', 'mistral', 'phi3', 'gemma2', 'codellama'],
    gemini: ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'],
    groq: [
      'meta-llama/llama-4-scout-17b-16e-instruct',
      'meta-llama/llama-4-maverick-17b-128e-instruct',
      'llama-3.3-70b-versatile',
      'llama-3.1-8b-instant',
      'mixtral-8x7b-32768',
    ],
    openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
    anthropic: ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'],
    xai: ['grok-3', 'grok-3-mini', 'grok-2-1212'],
  };

  // Returns the current model value for the selected provider
  function getCurrentModel(p: LLMProvider): string {
    if (p === 'ollama') return ollamaModel;
    if (p === 'gemini') return geminiModel;
    if (p === 'groq') return groqModel;
    if (p === 'openai') return openaiModel;
    if (p === 'anthropic') return anthropicModel;
    if (p === 'xai') return xaiModel;
    return '';
  }

  function setCurrentModel(p: LLMProvider, v: string) {
    if (p === 'ollama') ollamaModel = v;
    else if (p === 'gemini') geminiModel = v;
    else if (p === 'groq') groqModel = v;
    else if (p === 'openai') openaiModel = v;
    else if (p === 'anthropic') anthropicModel = v;
    else if (p === 'xai') xaiModel = v;
  }

  function getApiKeySet(p: LLMProvider): boolean {
    if (p === 'gemini') return geminiApiKeySet;
    if (p === 'groq') return groqApiKeySet;
    if (p === 'openai') return openaiApiKeySet;
    if (p === 'anthropic') return anthropicApiKeySet;
    if (p === 'xai') return xaiApiKeySet;
    return false;
  }

  // Reactive current model for the selected provider
  let currentModel = $derived(getCurrentModel(selectedProvider));

  async function loadConfig() {
    try {
      const cfg: LLMConfig = await apiService.getLLMConfig();
      activeProvider = cfg.provider;
      selectedProvider = cfg.provider;
      temperature = cfg.temperature ?? 0.1;
      ollamaBaseUrl = cfg.ollama_base_url;
      ollamaModel = cfg.ollama_model;
      geminiModel = cfg.gemini_model;
      geminiApiKeySet = cfg.gemini_api_key_set;
      groqModel = cfg.groq_model;
      groqApiKeySet = cfg.groq_api_key_set;
      openaiModel = cfg.openai_model;
      openaiApiKeySet = cfg.openai_api_key_set;
      anthropicModel = cfg.anthropic_model;
      anthropicApiKeySet = cfg.anthropic_api_key_set;
      xaiModel = cfg.xai_model;
      xaiApiKeySet = cfg.xai_api_key_set;
      activeModel = getCurrentModel(cfg.provider);
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
    } else if (selectedProvider === 'openai') {
      update.openai_model = openaiModel.trim() || undefined;
      if (openaiApiKey.trim()) update.openai_api_key = openaiApiKey.trim();
    } else if (selectedProvider === 'anthropic') {
      update.anthropic_model = anthropicModel.trim() || undefined;
      if (anthropicApiKey.trim()) update.anthropic_api_key = anthropicApiKey.trim();
    } else if (selectedProvider === 'xai') {
      update.xai_model = xaiModel.trim() || undefined;
      if (xaiApiKey.trim()) update.xai_api_key = xaiApiKey.trim();
    }

    try {
      const result = await apiService.updateLLMConfig(update);
      geminiApiKeySet = result.gemini_api_key_set;
      groqApiKeySet = result.groq_api_key_set;
      openaiApiKeySet = result.openai_api_key_set;
      anthropicApiKeySet = result.anthropic_api_key_set;
      xaiApiKeySet = result.xai_api_key_set;
      if (result.temperature != null) temperature = result.temperature;
      // Update active badge to reflect what's now actually running
      activeProvider = selectedProvider;
      activeModel = getCurrentModel(selectedProvider);
      // Clear plaintext key inputs
      geminiApiKey = '';
      groqApiKey = '';
      openaiApiKey = '';
      anthropicApiKey = '';
      xaiApiKey = '';
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
        <div class="flex items-center justify-between gap-6">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-[#443C68]/10 flex items-center justify-center shrink-0">
              <svg class="w-5 h-5 text-[#443C68]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m8-9h1M3 12H2m15.364-6.364l.707.707M5.929 18.071l-.707.707m12.142 0l-.707-.707M6.636 6.636l-.707-.707M12 18a6 6 0 100-12 6 6 0 000 12z" />
              </svg>
            </div>
            <div>
              <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">Appearance</h2>
              <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Choose a theme for the app.</p>
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
        <!-- Header row — same structure as Appearance -->
        <div class="flex items-center justify-between gap-6">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-[#443C68]/10 flex items-center justify-center shrink-0">
              <svg class="w-5 h-5 text-[#443C68]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.346a4 4 0 00-.999 1.354l-.142.49a2 2 0 01-1.93 1.474H10.88a2 2 0 01-1.93-1.474l-.141-.49a4 4 0 00-1-1.354l-.346-.346z" />
              </svg>
            </div>
            <div>
              <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">AI Model</h2>
              <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Choose your LLM provider and model.</p>
            </div>
          </div>

          <!-- Active badge — only reflects what's actually saved/running -->
          {#if !loading && activeModel}
            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium shrink-0
              bg-[#443C68]/10 text-[#443C68] dark:bg-[#443C68]/20 dark:text-purple-300">
              <span class="w-1.5 h-1.5 rounded-full bg-[#443C68] dark:bg-purple-400"></span>
              {PROVIDER_LABELS[activeProvider]} · {activeModel}
            </span>
          {:else if !loading}
            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium shrink-0
              bg-[#443C68]/10 text-[#443C68] dark:bg-[#443C68]/20 dark:text-purple-300">
              <span class="w-1.5 h-1.5 rounded-full bg-[#443C68] dark:bg-purple-400"></span>
              {PROVIDER_LABELS[activeProvider]}
            </span>
          {/if}
        </div>

        <!-- Form — always visible (uncollapsed) -->
        {#if loading}
          <div class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 mt-5">
            <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
            </svg>
            Loading configuration…
          </div>
        {:else}
          <div class="mt-5 pt-5 border-t border-gray-100 dark:border-gray-800 space-y-4">

            <!-- Provider + Model row -->
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="llm-provider" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Provider
                </label>
                <select
                  id="llm-provider"
                  bind:value={selectedProvider}
                  onchange={() => { saveState = 'idle'; }}
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                    focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                    transition-colors cursor-pointer"
                >
                  {#each Object.entries(PROVIDER_LABELS) as [val, label]}
                    <option value={val}>{label}</option>
                  {/each}
                </select>
              </div>

              <div>
                <label for="llm-model" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Model
                </label>
                {#if selectedProvider === 'ollama'}
                  <!-- Ollama: free text since installed models vary -->
                  <input
                    id="llm-model"
                    type="text"
                    bind:value={ollamaModel}
                    placeholder="e.g. tinyllama"
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                      bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                      placeholder-gray-400 dark:placeholder-gray-600
                      focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                      transition-colors"
                  />
                {:else}
                  <select
                    id="llm-model"
                    value={currentModel}
                    onchange={(e) => setCurrentModel(selectedProvider, (e.target as HTMLSelectElement).value)}
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                      bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100
                      focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68]
                      transition-colors cursor-pointer"
                  >
                    {#each MODEL_OPTIONS[selectedProvider] as m}
                      <option value={m}>{m}</option>
                    {/each}
                  </select>
                {/if}
              </div>
            </div>

            <!-- Ollama base URL (only for Ollama) -->
            {#if selectedProvider === 'ollama'}
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
            {:else}
              <!-- API Key for cloud providers -->
              <div>
                <label for="llm-api-key" class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  API Key
                  {#if getApiKeySet(selectedProvider)}
                    <span class="ml-1 font-normal text-green-600 dark:text-green-400">· configured</span>
                  {/if}
                </label>
                {#if selectedProvider === 'gemini'}
                  <input id="llm-api-key" type="password" bind:value={geminiApiKey}
                    placeholder={geminiApiKeySet ? 'Leave blank to keep existing key' : 'Enter your Gemini API key'}
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68] transition-colors" />
                {:else if selectedProvider === 'groq'}
                  <input id="llm-api-key" type="password" bind:value={groqApiKey}
                    placeholder={groqApiKeySet ? 'Leave blank to keep existing key' : 'Enter your Groq API key'}
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68] transition-colors" />
                {:else if selectedProvider === 'openai'}
                  <input id="llm-api-key" type="password" bind:value={openaiApiKey}
                    placeholder={openaiApiKeySet ? 'Leave blank to keep existing key' : 'Enter your OpenAI API key'}
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68] transition-colors" />
                {:else if selectedProvider === 'anthropic'}
                  <input id="llm-api-key" type="password" bind:value={anthropicApiKey}
                    placeholder={anthropicApiKeySet ? 'Leave blank to keep existing key' : 'Enter your Anthropic API key'}
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68] transition-colors" />
                {:else if selectedProvider === 'xai'}
                  <input id="llm-api-key" type="password" bind:value={xaiApiKey}
                    placeholder={xaiApiKeySet ? 'Leave blank to keep existing key' : 'Enter your xAI API key'}
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-[#37352F] dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-[#443C68]/30 focus:border-[#443C68] transition-colors" />
                {/if}
              </div>
            {/if}

            <!-- Temperature -->
            <div>
              <div class="flex items-center justify-between mb-2">
                <label for="llm-temperature" class="text-xs font-medium text-gray-700 dark:text-gray-300">
                  Temperature
                </label>
                <div class="flex items-center gap-2">
                  <span class="text-xs font-mono font-semibold text-[#443C68] dark:text-purple-300">
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
                  class="flex-1 h-2 rounded-full appearance-none cursor-pointer accent-[#443C68] bg-gray-200 dark:bg-gray-700"
                />
                <span class="text-xs text-gray-400 dark:text-gray-500 shrink-0">Creative</span>
              </div>
            </div>

            <!-- Save row -->
            <div class="flex items-center justify-between pt-1">
              {#if saveState === 'success'}
                <span class="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                  </svg>
                  Saved
                </span>
              {:else if saveState === 'error'}
                <span class="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
