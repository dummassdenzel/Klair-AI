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
    return response.data;
  },

  async getChatMessages(sessionId: number): Promise<ChatMessage[]> {
    const response = await apiClient.get(`/chat-sessions/${sessionId}/messages`);
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
};