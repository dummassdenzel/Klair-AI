import adapter from '@sveltejs/adapter-auto';
import adapterStatic from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// Detect if we're building for Tauri
const isTauri = process.env.TAURI_PLATFORM !== undefined;

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://svelte.dev/docs/kit/integrations
	// for more information about preprocessors
	preprocess: vitePreprocess(),

	kit: {
		// Use adapter-static for Tauri builds, adapter-auto for web
		adapter: isTauri 
			? adapterStatic({ 
				fallback: 'index.html',
				precompress: false,
				strict: false
			})
			: adapter()
	}
};

export default config;
