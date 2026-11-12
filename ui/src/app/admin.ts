import { Component, OnInit, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { forkJoin } from 'rxjs';
import { ApiService } from './api.service';
import { DocumentCounts, UsageLine } from './models';

/**
 * Admin view (FR-41): requests, refusals, tokens, cost, latency and time to first token by day and
 * by user, and documents by status. Users appear by their pseudonymous id; no question text is
 * shown because the API returns none. The server enforces the admin role; this page only reads.
 */
@Component({
  selector: 'app-admin',
  imports: [DecimalPipe],
  template: `
    <section class="card">
      <h1>Usage</h1>
      <label>
        Window
        <select [value]="days()" (change)="setDays($event)">
          <option value="1">Last day</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
          <option value="92">Last 92 days</option>
        </select>
      </label>
      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      } @else if (loading()) {
        <p class="muted">Loading…</p>
      } @else {
        @if (documents(); as d) {
          <h2>Documents ({{ d.total }})</h2>
          <p>
            @for (s of statuses; track s) {
              <span class="badge" [class]="s">{{ s }}: {{ d.by_status[s] }}</span>&nbsp;
            }
          </p>
        }
        @for (table of tables(); track table.title) {
          <h2>{{ table.title }}</h2>
          @if (table.rows.length === 0) {
            <p class="muted">No questions in this window.</p>
          } @else {
            <table>
              <thead>
                <tr>
                  <th>{{ table.keyLabel }}</th><th>Questions</th><th>Refused</th><th>Prompt tokens</th>
                  <th>Completion tokens</th><th>Cost (USD)</th><th>Latency p50 / p95</th>
                  <th>First token p50 / p95</th>
                </tr>
              </thead>
              <tbody>
                @for (r of table.rows; track r.key) {
                  <tr>
                    <td>{{ r.key }}</td>
                    <td>{{ r.requests }}</td>
                    <td>{{ r.refused }}</td>
                    <td>{{ r.prompt_tokens ?? '–' }}</td>
                    <td>{{ r.completion_tokens ?? '–' }}</td>
                    <td>{{ r.cost_usd === null ? '–' : (r.cost_usd | number: '1.4-6') }}</td>
                    <td>{{ ms(r.latency_p50_ms) }} / {{ ms(r.latency_p95_ms) }}</td>
                    <td>{{ ms(r.ttft_p50_ms) }} / {{ ms(r.ttft_p95_ms) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          }
        }
        <p class="muted">
          Tokens and cost are empty for answers recorded before token counting, and cost is empty
          when no price is configured. Users are shown by their pseudonymous id.
        </p>
      }
    </section>
  `,
})
export class Admin implements OnInit {
  private readonly api = inject(ApiService);

  protected readonly statuses = ['ready', 'pending', 'processing', 'failed'] as const;
  protected readonly days = signal(7);
  protected readonly loading = signal(true);
  protected readonly error = signal('');
  protected readonly documents = signal<DocumentCounts | null>(null);
  protected readonly tables = signal<{ title: string; keyLabel: string; rows: UsageLine[] }[]>([]);

  ngOnInit(): void {
    this.load();
  }

  protected setDays(event: Event): void {
    this.days.set(Number((event.target as HTMLSelectElement).value));
    this.load();
  }

  protected ms(value: number | null): string {
    if (value === null) return '–';
    return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`;
  }

  private load(): void {
    this.loading.set(true);
    this.error.set('');
    forkJoin({
      byDay: this.api.adminUsage('day', this.days()),
      byUser: this.api.adminUsage('user', this.days()),
      documents: this.api.adminDocuments(),
    }).subscribe({
      next: ({ byDay, byUser, documents }) => {
        this.documents.set(documents);
        this.tables.set([
          { title: 'By day (UTC)', keyLabel: 'Day', rows: [...byDay.rows].reverse() },
          { title: 'By user', keyLabel: 'User id', rows: byUser.rows },
        ]);
        this.loading.set(false);
      },
      error: (e) => {
        this.loading.set(false);
        this.error.set(e.status === 403 ? 'This page is for administrators.' : 'Could not load usage.');
      },
    });
  }
}
