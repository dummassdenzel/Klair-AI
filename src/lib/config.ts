// Environment configuration
export const config = {
  // API Configuration — single source of truth for the backend base URL.
  // Override with VITE_API_BASE_URL in .env (consumed by src/lib/api/client.ts).
  api: {
    baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api',
    timeout: 30000,
  },
};
