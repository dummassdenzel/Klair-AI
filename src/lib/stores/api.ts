import { writable, derived } from 'svelte/store';
import type { SystemStatus, ChatSession, DocumentStats } from '../api/types';

// System State Store
export const systemStatus = writable<SystemStatus | null>(null);
export const isLoading = writable(false);
export const error = writable<string | null>(null);

// Chat State Store
export const currentChatSession = writable<ChatSession | null>(null);
export const chatHistory = writable<ChatSession[]>([]);
export const isChatLoading = writable(false);
export const isIndexingInProgress = writable(false);
export const contentIndexingInProgress = writable(false); // Separate flag for content indexing
export const metadataIndexed = writable(false); // Flag for metadata completion

// Document State Store
export const documentStats = writable<DocumentStats | null>(null);
export const isDocumentsLoading = writable(false);

// Derived Stores
export const isSystemReady = derived(
  [systemStatus],
  ([$status]) => $status?.processor_ready && $status?.directory_set
);

export const currentDirectory = derived(
  [systemStatus],
  ([$status]) => $status?.current_directory || null
);

// Store Actions
export const apiActions = {
  setError(message: string) {
    error.set(message);
    setTimeout(() => error.set(null), 5000); // Auto-clear after 5s
  },

  clearError() {
    error.set(null);
  },

  setLoading(loading: boolean) {
    isLoading.set(loading);
  },

  setChatLoading(loading: boolean) {
    isChatLoading.set(loading);
  },

  setDocumentsLoading(loading: boolean) {
    isDocumentsLoading.set(loading);
  },
};