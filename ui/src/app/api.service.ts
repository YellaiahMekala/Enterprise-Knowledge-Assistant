import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  ChatRequest,
  Citation,
  Conversation,
  DocumentCounts,
  DocumentItem,
  Message,
  Problem,
  UsageReport,
} from './models';
import { SessionService } from './session.service';
import { OidcClient } from './oidc';
import { SseEvent, parseSse } from './sse';

export class ApiError extends Error {
  constructor(readonly problem: Problem) {
    super(problem.detail ?? problem.title);
  }
}

interface StoredMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  refusal_reason: string | null;
}

export interface ConversationDetail extends Conversation {
  messages: StoredMessage[];
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly session = inject(SessionService);
  private readonly oidc = inject(OidcClient);

  /** With ``apiKey``, checks that key before it is stored (sign-in); otherwise uses the session. */
  me(apiKey?: string) {
    const headers: Record<string, string> = apiKey ? { 'X-API-Key': apiKey } : {};
    return this.http.get<{ user_id: string; role: string }>('/api/v1/me', { headers });
  }

  /** Admin only (403 otherwise): usage by user or by UTC day over the last `days` days. */
  adminUsage(groupBy: 'user' | 'day', days: number): Observable<UsageReport> {
    const to = new Date();
    const from = new Date(to.getTime() - days * 86_400_000);
    return this.http.get<UsageReport>('/api/v1/admin/usage', {
      params: { group_by: groupBy, from: from.toISOString(), to: to.toISOString() },
    });
  }

  adminDocuments(): Observable<DocumentCounts> {
    return this.http.get<DocumentCounts>('/api/v1/admin/documents');
  }

  documents(): Observable<{ items: DocumentItem[] }> {
    return this.http.get<{ items: DocumentItem[] }>('/api/v1/documents', {
      params: { limit: 100 },
    });
  }

  upload(file: File): Observable<DocumentItem> {
    const body = new FormData();
    body.append('file', file);
    return this.http.post<DocumentItem>('/api/v1/documents', body);
  }

  deleteDocument(id: string) {
    return this.http.delete<void>(`/api/v1/documents/${id}`);
  }

  conversations() {
    return this.http.get<{ items: Conversation[] }>('/api/v1/conversations');
  }

  conversation(id: string) {
    return this.http.get<ConversationDetail>(`/api/v1/conversations/${id}`);
  }

  deleteConversation(id: string) {
    return this.http.delete<void>(`/api/v1/conversations/${id}`);
  }

  // HttpClient cannot read a response body as it arrives, so the streamed chat uses fetch.
  async *chat(request: ChatRequest, signal: AbortSignal): AsyncGenerator<SseEvent> {
    await this.session.fresh((token) => this.oidc.refresh(token));
    const response = await fetch('/api/v1/chat', {
      method: 'POST',
      signal,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...this.session.authHeaders(),
      },
      body: JSON.stringify({ ...request, stream: true }),
    });
    if (!response.ok || !response.body) {
      const problem = await response
        .json()
        .catch(() => ({ status: response.status, title: response.statusText }));
      throw new ApiError(problem);
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let pending = '';
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        const parsed = parseSse(pending + value);
        pending = parsed.rest;
        yield* parsed.events;
      }
    } finally {
      reader.cancel().catch(() => undefined);
    }
  }
}

export function toMessage(m: StoredMessage): Message {
  return {
    role: m.role,
    content: m.content,
    citations: m.citations,
    refused: m.refusal_reason !== null,
    refusalReason: m.refusal_reason,
  };
}
