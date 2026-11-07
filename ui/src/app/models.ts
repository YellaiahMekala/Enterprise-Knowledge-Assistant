export type Mode = 'verified' | 'fast';
export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed';

export interface Citation {
  chunk_id: string;
  document_id: string;
  filename: string;
  index: number;
  locator: Record<string, unknown>;
  quote: string;
}

export interface DocumentItem {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  chunk_count: number | null;
  page_count: number | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  refused?: boolean;
  refusalReason?: string | null;
  verified?: boolean;
  provisional?: boolean;
}

export interface ChatRequest {
  question: string;
  conversation_id?: string | null;
  mode?: Mode;
  top_k?: number;
}

export interface Problem {
  status: number;
  title: string;
  detail?: string;
}
