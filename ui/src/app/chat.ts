// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiError, ApiService, toMessage } from './api.service';
import { applyEvent, startAnswer } from './chat-state';
import { Citation, Conversation, Message, Mode } from './models';

@Component({
  selector: 'app-chat',
  imports: [FormsModule, DatePipe],
  template: `
    <div class="chat">
      <aside class="card">
        <button (click)="newChat()">New chat</button>
        <ul class="conversations">
          @for (c of conversations(); track c.id) {
            <li [class.active]="c.id === conversationId()">
              <button class="link" (click)="open(c)">{{ c.title || 'Untitled' }}</button>
              <button class="link danger" aria-label="Delete conversation" (click)="remove(c)">×</button>
            </li>
          }
        </ul>
      </aside>

      <section class="card thread">
        <div class="messages" aria-live="polite">
          @for (m of messages(); track $index) {
            <article [class]="m.role">
              <p>{{ m.content }}@if (m.provisional) { <span class="cursor">▍</span> }</p>
              @if (m.provisional) {
                <small class="muted">Streaming. Citations are checked when the answer finishes.</small>
              }
              @if (m.refused) {
                <small class="muted">Not answered: {{ m.refusalReason }}</small>
              }
              @if (m.citations.length > 0) {
                <ol class="citations">
                  @for (c of m.citations; track c.chunk_id) {
                    <li>
                      @if (c.kind === 'web' && c.source_url) {
                        <strong>[{{ c.index }}] <a [href]="c.source_url" target="_blank" rel="noopener noreferrer">{{ c.source_url }}</a></strong>
                        <small class="muted">web page, fetched {{ c.fetched_at | date: 'medium' }}</small>
                      } @else {
                        <strong>[{{ c.index }}] {{ c.filename }}</strong> {{ where(c) }}
                      }
                      <blockquote>{{ c.quote }}</blockquote>
                    </li>
                  }
                </ol>
              }
            </article>
          } @empty {
            <p class="muted">Ask a question about your documents.</p>
          }
        </div>

        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }

        <form class="composer" (ngSubmit)="send()">
          <textarea name="q" rows="2" maxlength="1000" [ngModel]="question()" (ngModelChange)="question.set($event)" placeholder="Your question"
            (keydown.enter)="enter($event)" [disabled]="busy()"></textarea>
          <select name="mode" [(ngModel)]="mode" aria-label="Answer mode">
            <option value="verified">Verified (checked before it appears)</option>
            <option value="fast">Fast (streams now, checked after)</option>
          </select>
          @if (busy()) {
            <button type="button" (click)="stop()">Stop</button>
          } @else {
            <button type="submit" [disabled]="!question().trim()">Send</button>
          }
        </form>
      </section>
    </div>
  `,
})
export class Chat implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private abort?: AbortController;

  protected readonly conversations = signal<Conversation[]>([]);
  protected readonly conversationId = signal<string | null>(null);
  protected readonly messages = signal<Message[]>([]);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly question = signal('');
  protected mode: Mode = 'verified';

  ngOnInit(): void {
    this.loadConversations();
  }

  ngOnDestroy(): void {
    this.abort?.abort();
  }

  private loadConversations(): void {
    this.api.conversations().subscribe({ next: ({ items }) => this.conversations.set(items) });
  }

  protected newChat(): void {
    this.abort?.abort();
    this.conversationId.set(null);
    this.messages.set([]);
    this.error.set('');
  }

  protected open(c: Conversation): void {
    this.abort?.abort();
    this.error.set('');
    this.api.conversation(c.id).subscribe({
      next: (detail) => {
        this.conversationId.set(detail.id);
        this.messages.set(detail.messages.map(toMessage));
      },
      error: () => this.error.set('Could not open that conversation.'),
    });
  }

  protected remove(c: Conversation): void {
    this.api.deleteConversation(c.id).subscribe({
      next: () => {
        if (c.id === this.conversationId()) this.newChat();
        this.loadConversations();
      },
    });
  }

  protected enter(event: Event): void {
    if (!(event as KeyboardEvent).shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  protected stop(): void {
    this.abort?.abort();
  }

  protected async send(): Promise<void> {
    const question = this.question().trim();
    if (!question || this.busy()) return;
    this.question.set('');
    this.error.set('');
    this.busy.set(true);
    this.abort = new AbortController();

    this.messages.update((list) => [...list, { role: 'user', content: question, citations: [] }]);
    let state = startAnswer(this.conversationId());
    this.messages.update((list) => [...list, state.answer]);

    try {
      for await (const event of this.api.chat(
        { question, conversation_id: this.conversationId(), mode: this.mode },
        this.abort.signal,
      )) {
        state = applyEvent(state, event);
        this.messages.update((list) => [...list.slice(0, -1), state.answer]);
        if (state.conversationId) this.conversationId.set(state.conversationId);
        if (state.error) this.error.set(state.error);
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        this.error.set(e instanceof ApiError ? e.message : 'The connection was lost.');
      }
    } finally {
      this.busy.set(false);
      // Drop an empty placeholder (stopped or failed before any text arrived).
      this.messages.update((list) => (list.at(-1)?.content === '' ? list.slice(0, -1) : list));
      this.loadConversations();
    }
  }

  protected where(c: Citation): string {
    const l = c.locator;
    switch (l['type']) {
      case 'page':
        return `(page ${l['page']})`;
      case 'lines':
        return `(lines ${l['start']}-${l['end']})`;
      case 'rows':
        return `(rows ${l['start']}-${l['end']})`;
      default:
        return '';
    }
  }
}
