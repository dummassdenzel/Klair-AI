import { writable } from 'svelte/store';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'theme';

export const theme = writable<Theme>('light');

function getPreferredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // ignore
  }

  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  return 'light';
}

export function applyTheme(next: Theme) {
  theme.set(next);
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // ignore
  }

  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('dark', next === 'dark');
  }
}

export function initTheme() {
  applyTheme(getPreferredTheme());
}

