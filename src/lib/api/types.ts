// Chat Types
export interface ChatRequest {
    session_id: number;
    message: string;
  }
  
  export interface ChatResponse {
    message: string;
    sources: DocumentSource[];
    response_time: number;
  }
  
  export interface DocumentSource {
    file_path: string;
    relevance_score: number;
    content_snippet: string;
    chunks_found: number;
    file_type: string;
  }
  
  // Directory & Status Types
  export interface DirectoryResponse {
    status: string;
    message: string;
    directory: string;
    processing_status: string;
  }
  
  export interface SystemStatus {
    directory_set: boolean;
    current_directory: string | null;
    processor_ready: boolean;
    file_monitor_status: string;
    database_stats: {
      total_documents: number;
      status_breakdown: Record<string, number>;
      type_breakdown: Record<string, number>;
    };
  }
  
  // Document Types
  export interface DocumentStats {
    total_documents: number;
    status_breakdown: Record<string, number>;
    type_breakdown: Record<string, number>;
  }
  
  export interface IndexedDocument {
    id: number;
    file_path: string;
    file_type: string;
    file_size: number;
    last_modified: string;
    content_preview: string;
    processing_status: string;
    chunks_count?: number;
    indexed_at?: string;
  }

  export interface SearchResult {
    status: string;
    documents: {
      documents: IndexedDocument[];
      total_count: number;
      limit: number;
      offset: number;
      has_more: boolean;
    };
  }
  
  // Chat Session Types
  export interface ChatSession {
    id: number;
    title: string;
    directory_path: string;
    created_at: string;
    updated_at: string;
    message_count: number;
  }
  
  export interface ChatMessage {
    id: number;
    session_id: number;
    user_message: string;
    ai_response: string;
    sources: DocumentSource[];
    response_time: number;
    timestamp: string;
  }