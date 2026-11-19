// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ApiService } from './api.service';
import { DocumentItem } from './models';

const POLL_MS = 3000;
const ACCEPT = '.pdf,.docx,.csv,.md,.txt';

@Component({
  selector: 'app-documents',
  imports: [DatePipe],
  template: `
    <section class="card">
      <h1>Documents</h1>
      <label class="upload">
        <input type="file" [accept]="accept" (change)="upload($event)" [disabled]="uploading()" />
        <span>{{ uploading() ? 'Uploading…' : 'Choose a file to upload (PDF, DOCX, CSV, Markdown, text)' }}</span>
      </label>
      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
      @if (documents().length === 0) {
        <p class="muted">No documents yet.</p>
      } @else {
        <table>
          <thead>
            <tr><th>Name</th><th>Status</th><th>Chunks</th><th>Size</th><th></th></tr>
          </thead>
          <tbody>
            @for (d of documents(); track d.id) {
              <tr>
                <td>{{ d.filename }}
                  @if (d.source_url) { <small class="muted">web page, fetched {{ d.fetched_at | date: 'short' }}</small> }</td>
                <td><span class="badge" [class]="d.status">{{ d.status }}</span>
                  @if (d.error_code) { <small class="muted">{{ d.error_code }}</small> }</td>
                <td>{{ d.chunk_count ?? '–' }}</td>
                <td>{{ size(d.size_bytes) }}</td>
                <td><button class="link" (click)="remove(d)">Delete</button></td>
              </tr>
            }
          </tbody>
        </table>
      }
    </section>
  `,
})
export class Documents implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private timer?: ReturnType<typeof setTimeout>;

  protected readonly accept = ACCEPT;
  protected readonly documents = signal<DocumentItem[]>([]);
  protected readonly uploading = signal(false);
  protected readonly error = signal('');

  ngOnInit(): void {
    this.refresh();
  }

  ngOnDestroy(): void {
    clearTimeout(this.timer);
  }

  // Keeps polling while any document is still being processed.
  private refresh(): void {
    this.api.documents().subscribe({
      next: ({ items }) => {
        this.documents.set(items);
        const busy = items.some((d) => d.status === 'pending' || d.status === 'processing');
        clearTimeout(this.timer);
        if (busy) this.timer = setTimeout(() => this.refresh(), POLL_MS);
      },
      error: () => this.error.set('Could not load documents.'),
    });
  }

  protected upload(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.uploading.set(true);
    this.error.set('');
    this.api.upload(file).subscribe({
      next: () => {
        this.uploading.set(false);
        input.value = '';
        this.refresh();
      },
      error: (e) => {
        this.uploading.set(false);
        input.value = '';
        this.error.set(e.error?.detail ?? 'Upload failed.');
      },
    });
  }

  protected remove(doc: DocumentItem): void {
    if (!confirm(`Delete ${doc.filename}?`)) return;
    this.api.deleteDocument(doc.id).subscribe({
      next: () => this.refresh(),
      error: () => this.error.set('Could not delete the document.'),
    });
  }

  protected size(bytes: number): string {
    return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
  }
}
