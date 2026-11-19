// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { Citation, Message } from './models';
import { SseEvent } from './sse';

export interface ChatState {
  conversationId: string | null;
  answer: Message;
  error: string | null;
}

export function startAnswer(conversationId: string | null): ChatState {
  return { conversationId, answer: { role: 'assistant', content: '', citations: [] }, error: null };
}

interface Done {
  answer: string;
  citations: Citation[];
  refused: boolean;
  refusal_reason: string | null;
  verified: boolean;
}

// Folds one stream event into the state. Fast mode streams provisional text that `replace` or
// `done` may overwrite; verified mode sends the whole checked answer in a single token event.
export function applyEvent(state: ChatState, event: SseEvent): ChatState {
  const data = event.data as Record<string, unknown>;
  switch (event.event) {
    case 'meta':
      return { ...state, conversationId: data['conversation_id'] as string };
    case 'token':
      return {
        ...state,
        answer: {
          ...state.answer,
          content: state.answer.content + (data['text'] as string),
          provisional: data['provisional'] === true,
        },
      };
    case 'replace':
      return { ...state, answer: { ...state.answer, content: data['text'] as string } };
    case 'done': {
      const done = data as unknown as Done;
      return {
        ...state,
        answer: {
          role: 'assistant',
          content: done.answer,
          citations: done.citations,
          refused: done.refused,
          refusalReason: done.refusal_reason,
          verified: done.verified,
          provisional: false,
        },
      };
    }
    case 'error':
      return { ...state, error: (data['detail'] as string) ?? 'The request failed.' };
    default:
      return state;
  }
}
