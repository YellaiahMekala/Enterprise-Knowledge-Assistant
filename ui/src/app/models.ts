// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
export type Mode = 'verified' | 'fast';
export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed';

export interface Citation {
  chunk_id: string;
  document_id: string;
  filename: string;
  index: number;
  locator: Record<string, unknown>;
  quote: string;
  kind?: 'document' | 'web';
  source_url?: string | null;
  fetched_at?: string | null;
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
  source_url?: string | null;
  fetched_at?: string | null;
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

/** One user or one UTC day in the admin usage report (counts and timings only, never text). */
export interface UsageLine {
  key: string;
  requests: number;
  refused: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cost_usd: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  ttft_p50_ms: number | null;
  ttft_p95_ms: number | null;
}

export interface UsageReport {
  group_by: 'user' | 'day';
  start: string;
  end: string;
  rows: UsageLine[];
}

export interface DocumentCounts {
  total: number;
  by_status: Record<DocumentStatus, number>;
}
