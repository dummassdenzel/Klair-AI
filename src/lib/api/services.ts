import apiClient from './client';
import type {
  ChatRequest,
  ChatResponse,
  DirectoryResponse,
  SystemStatus,
  DocumentStats,
  SearchResult,
  ChatSession,
  ChatMessage,
} from './types';

// Core API Services
export const apiService = {
  // Directory Management
  async selectDirectory(): Promise<any> {
    const response = await apiClient.get('/select-directory');
    return response.data;
  },

  async setDirectory(directoryPath: string): Promise<DirectoryResponse> {
    const response = await apiClient.post('/set-directory', { path: directoryPath });
    return response.data;
  },

  async getStatus(): Promise<SystemStatus> {
    const response = await apiClient.get('/status');
    return response.data;
  },

  // Chat Operations
  async sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
    const response = await apiClient.post('/chat', request);
    return response.data;
  },

  // Document Management
  async getDocumentStats(): Promise<DocumentStats> {
    const response = await apiClient.get('/documents/stats');
    return response.data;
  },

  async searchDocuments(params: {
    query?: string;
    file_type?: string;
    limit?: number;
    offset?: number;
  }): Promise<SearchResult> {
    const response = await apiClient.get('/documents/search', { params });
    return response.data;
  },

  async clearIndex(): Promise<{ status: string; message: string }> {
    const response = await apiClient.post('/clear-index');
    return response.data;
  },

  // Chat Session Management
  async getChatSessions(): Promise<ChatSession[]> {
    const response = await apiClient.get('/chat-sessions');
    // Fix: Extract sessions from the nested response structure
    return response.data.sessions || [];
  },

  async createChatSession(directoryPath: string, title: string): Promise<ChatSession> {
    const response = await apiClient.post('/chat-sessions', { title });
    return response.data;
  },

  async getChatMessages(sessionId: number): Promise<any> {
    console.log('🔍 API Service: Getting messages for session:', sessionId);
    const response = await apiClient.get(`/chat-sessions/${sessionId}/messages`);
    console.log('🔍 API Service: Raw messages response:', response);
    console.log('🔍 API Service: Messages data:', response.data);
    
    // FIX: Return the entire response object, not just messages
    return response.data;
  },

  async updateChatSessionTitle(sessionId: number, title: string): Promise<ChatSession> {
    const response = await apiClient.put(`/chat-sessions/${sessionId}/title`, { title });
    return response.data;
  },

  async deleteChatSession(sessionId: number): Promise<{ status: string; message: string }> {
    const response = await apiClient.delete(`/chat-sessions/${sessionId}`);
    return response.data;
  },

  // Configuration
  async getConfiguration(): Promise<Record<string, any>> {
    const response = await apiClient.get('/configuration');
    return response.data;
  },

  async updateConfiguration(config: Record<string, any>): Promise<Record<string, any>> {
    const response = await apiClient.post('/update-configuration', config);
    return response.data;
  },

  // Metrics Dashboard
  async getMetricsSummary(timeWindowMinutes: number = 60): Promise<any> {
    const response = await apiClient.get('/metrics/summary', {
      params: { time_window_minutes: timeWindowMinutes }
    });
    return response.data;
  },

  async getRetrievalStats(timeWindowMinutes: number = 60): Promise<any> {
    const response = await apiClient.get('/metrics/retrieval-stats', {
      params: { time_window_minutes: timeWindowMinutes }
    });
    return response.data;
  },

  async getTimeSeries(
    metricType: string = 'response_time',
    timeWindowMinutes: number = 60,
    bucketMinutes: number = 5
  ): Promise<any> {
    const response = await apiClient.get('/metrics/time-series', {
      params: {
        metric_type: metricType,
        time_window_minutes: timeWindowMinutes,
        bucket_minutes: bucketMinutes
      }
    });
    return response.data;
  },

  async getRecentQueries(limit: number = 20): Promise<any> {
    const response = await apiClient.get('/metrics/recent-queries', {
      params: { limit }
    });
    return response.data;
  },

  async getCounters(): Promise<any> {
    const response = await apiClient.get('/metrics/counters');
    return response.data;
  },

  // RAG Analytics
  async getQueryPatterns(timeWindowMinutes: number = 60): Promise<any> {
    const response = await apiClient.get('/analytics/query-patterns', {
      params: { time_window_minutes: timeWindowMinutes }
    });
    return response.data;
  },

  async getDocumentUsage(): Promise<any> {
    const response = await apiClient.get('/analytics/document-usage');
    return response.data;
  },

  async getRetrievalEffectiveness(timeWindowMinutes: number = 60): Promise<any> {
    const response = await apiClient.get('/analytics/retrieval-effectiveness', {
      params: { time_window_minutes: timeWindowMinutes }
    });
    return response.data;
  },

  async getPerformanceTrends(timeWindowMinutes: number = 60, buckets: number = 6): Promise<any> {
    const response = await apiClient.get('/analytics/performance-trends', {
      params: {
        time_window_minutes: timeWindowMinutes,
        buckets
      }
    });
    return response.data;
  },

  async getQuerySuccess(timeWindowMinutes: number = 60): Promise<any> {
    const response = await apiClient.get('/analytics/query-success', {
      params: { time_window_minutes: timeWindowMinutes }
    });
    return response.data;
  },
};