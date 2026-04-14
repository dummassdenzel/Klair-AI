<script lang="ts">
  import { theme, applyTheme, type Theme } from '$lib/stores/theme';

  function setTheme(next: Theme) {
    applyTheme(next);
  }
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
      <!-- Appearance -->
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
                <p class="text-xs text-gray-600 dark:text-gray-400 mt-1">
                  Choose a theme for the app.
                </p>
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
            >
              Light
            </button>
            <button
              type="button"
              onclick={() => setTheme('dark')}
              class="px-4 py-2 text-xs rounded-lg transition-colors font-medium
                {$theme === 'dark'
                  ? 'bg-white dark:bg-gray-950 text-[#37352F] dark:text-gray-100 shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-[#37352F] dark:hover:text-white'}"
              aria-pressed={$theme === 'dark'}
            >
              Dark
            </button>
          </div>
        </div>
      </div>

      <!-- Placeholder section to match structure -->
      <div class="bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-2xl p-6 shadow-sm">
        <h2 class="text-sm font-semibold text-[#37352F] dark:text-gray-100">About</h2>
        <p class="text-xs text-gray-600 dark:text-gray-400 mt-2">
          Klair AI settings will expand here over time.
        </p>
      </div>
    </div>
  </div>
</div>

