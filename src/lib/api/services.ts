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
  LLMConfig,
  LLMConfigUpdate,
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

  /**
   * Stream chat response via SSE. Callbacks: onMeta(sources, sessionId), onToken(delta), onDone(message, responseTime), onError(detail).
   */
  async sendChatMessageStream(
    request: ChatRequest,
    callbacks: {
      onMeta?: (sources: ChatResponse['sources'], sessionId: number) => void;
      onToken?: (delta: string) => void;
      onDone?: (message: string, responseTime: number) => void;
      onError?: (detail: string) => void;
      onEditProposal?: (proposal: import('./types').EditProposal) => void;
    }
  ): Promise<void> {
    const baseURL = apiClient.defaults.baseURL ?? '';
    const url = `${baseURL}/chat/stream`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      callbacks.onError?.(err.detail ?? 'Request failed');
      return;
    }
    const reader = res.body?.getReader();
    if (!reader) {
      callbacks.onError?.('No response body');
      return;
    }
    const decoder = new TextDecoder();
    let buffer = '';
    let pendingError: string | null = null;

    outer: while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      let event = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          event = line.slice(7).trim();
        } else if (line.startsWith('data: ') && event) {
          let data: Record<string, unknown> = {};
          try {
            data = JSON.parse(line.slice(6)) as Record<string, unknown>;
          } catch (_) {
            event = '';
            continue;
          }
          if (event === 'meta') {
            callbacks.onMeta?.((data.sources as ChatResponse['sources']) ?? [], (data.session_id as number) ?? 0);
          } else if (event === 'edit_proposal') {
            callbacks.onEditProposal?.(data as unknown as import('./types').EditProposal);
          } else if (event === 'token') {
            callbacks.onToken?.((data.delta as string) ?? '');
          } else if (event === 'done') {
            callbacks.onDone?.((data.message as string) ?? '', (data.response_time as number) ?? 0);
          } else if (event === 'error') {
            pendingError = (data.detail as string) ?? 'Unknown error';
            break outer;
          }
          event = '';
        }
      }
    }

    if (pendingError !== null) {
      callbacks.onError?.(pendingError);
    }
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

  async getDocumentMetadata(documentId: number): Promise<any> {
    const response = await apiClient.get(`/documents/${documentId}`);
    return response.data;
  },

  async getDocumentFile(documentId: number): Promise<Blob> {
    const response = await apiClient.get(`/documents/${documentId}/file`, {
      responseType: 'blob'
    });
    return response.data;
  },

  async clearIndex(): Promise<{ status: string; message: string }> {
    const response = await apiClient.post('/clear-index');
    return response.data;
  },

  async getIndexingProgress(): Promise<{ total: number; processed: number; failed: number; is_active: boolean }> {
    const response = await apiClient.get('/indexing/progress');
    return response.data.progress;
  },

  async applyEditProposal(proposalId: string): Promise<{ status: string; message: string; applied_changes: number; backup_path: string }> {
    const response = await apiClient.post('/documents/edit/apply', { proposal_id: proposalId });
    return response.data;
  },

  async discardEditProposal(proposalId: string): Promise<{ status: string }> {
    const response = await apiClient.post('/documents/edit/discard', { proposal_id: proposalId });
    return response.data;
  },

  async getSuggestions(): Promise<string[]> {
    const response = await apiClient.get('/chat/suggestions');
    return (response.data.suggestions as string[]) ?? [];
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

  // Phase 3: Update Queue Management
  async getUpdateQueueStatus(): Promise<any> {
    const response = await apiClient.get('/updates/queue');
    return response.data;
  },

  async getUpdateStatus(filePath: string): Promise<any> {
    const response = await apiClient.get(`/updates/status/${encodeURIComponent(filePath)}`);
    return response.data;
  },

  async forceUpdate(filePath: string): Promise<any> {
    const response = await apiClient.post('/updates/force', { file_path: filePath });
    return response.data;
  },

  // Phase 3: Server-Sent Events for real-time updates (more efficient than polling)
  createUpdateStream(callback: (data: any) => void): EventSource | null {
    try {
      const eventSource = new EventSource('http://localhost:8000/api/updates/stream');
      
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          callback(data);
        } catch (error) {
          console.error('Error parsing SSE data:', error);
        }
      };
      
      eventSource.onerror = (error) => {
        console.error('SSE connection error:', error);
        // Will automatically reconnect
      };
      
      return eventSource;
    } catch (error) {
      console.error('Failed to create SSE stream:', error);
      return null;
    }
  },

  // File operations
  async renameFile(filePath: string, newName: string): Promise<{ status: string; new_path: string }> {
    const response = await apiClient.post('/files/rename', { file_path: filePath, new_name: newName });
    return response.data;
  },

  async deleteFile(filePath: string): Promise<{ status: string }> {
    const response = await apiClient.post('/files/delete', { file_path: filePath });
    return response.data;
  },

  async moveFile(filePath: string, destinationDir: string): Promise<{ status: string; new_path: string }> {
    const response = await apiClient.post('/files/move', { file_path: filePath, destination_dir: destinationDir });
    return response.data;
  },

  async getFolders(): Promise<{ root: string; tree: import('./types').FolderNode }> {
    const response = await apiClient.get('/files/folders');
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

  async getFollowUpSuggestions(question: string, answer: string): Promise<string[]> {
    try {
      const response = await apiClient.post('/chat/follow-up-suggestions', { question, answer });
      return response.data?.suggestions ?? [];
    } catch {
      return [];
    }
  },

  // LLM provider configuration
  async getLLMConfig(): Promise<LLMConfig> {
    const response = await apiClient.get('/llm/config');
    return response.data;
  },

  async updateLLMConfig(update: LLMConfigUpdate): Promise<LLMConfig> {
    const response = await apiClient.post('/llm/config', update);
    return response.data;
  },

};