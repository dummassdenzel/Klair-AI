import axios, { type AxiosInstance, type AxiosResponse } from 'axios';
import { config } from '$lib/config';

// Create axios instance with base configuration
const apiClient: AxiosInstance = axios.create({
  baseURL: config.api.baseURL,
  timeout: 60000, // 60 seconds for LLM responses (increased for conversation history)
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for logging
apiClient.interceptors.request.use(
  (config) => {
    console.log(`🚀 API Request: ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error) => {
    console.error('❌ Request Error:', error);
    return Promise.reject(error);
  }
);

// Response interceptor: surface backend error message so UI can show it (403, 429, 413, etc.)
function getResponseMessage(error: any): string | undefined {
  const data = error.response?.data;
  if (!data) return undefined;
  const detail = data.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((e: any) => e.msg ?? e.message).filter(Boolean).join(' ') || undefined;
  return data.error ?? undefined;
}

apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    console.log(`✅ API Response: ${response.status} ${response.config.url}`);
    return response;
  },
  (error) => {
    const msg = getResponseMessage(error);
    if (msg) error.message = msg;
    console.error('❌ Response Error:', error.response?.data || error.message);
    return Promise.reject(error);
  }
);

export default apiClient;