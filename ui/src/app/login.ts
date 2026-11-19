// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from './api.service';
import { AUTH_CONFIG } from './auth-config';
import { OidcClient } from './oidc';
import { SessionService } from './session.service';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  template: `
    <section class="card narrow">
      <h1>Sign in</h1>
      @if (sso) {
        <p class="muted">Sign in with your organisation account.</p>
        <button type="button" (click)="signInWithSso()" [disabled]="busy()">
          Sign in with single sign-on
        </button>
      } @else {
        <p class="muted">Paste your API key. It is kept for this browser tab only.</p>
        <form (ngSubmit)="submit()">
          <input
            type="password"
            name="key"
            [ngModel]="key()"
            (ngModelChange)="key.set($event)"
            placeholder="API key"
            autocomplete="off"
            required
          />
          <button type="submit" [disabled]="busy() || !key()">Continue</button>
        </form>
      }
      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
    </section>
  `,
})
export class Login {
  private readonly api = inject(ApiService);
  private readonly session = inject(SessionService);
  private readonly router = inject(Router);
  private readonly oidc = inject(OidcClient);

  protected readonly sso = AUTH_CONFIG.mode === 'oidc';
  protected readonly key = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  protected async signInWithSso(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      location.assign(await this.oidc.authorizeUrl());
    } catch (e) {
      this.busy.set(false);
      this.error.set(e instanceof Error ? e.message : 'Could not start sign-in.');
    }
  }

  protected submit(): void {
    this.busy.set(true);
    this.error.set('');
    // The key is checked before it is stored: storing it first signed the app in, and the
    // shell's admin check then sent the rejected key a second time (found by the P16 browser test).
    const key = this.key().trim();
    this.api.me(key).subscribe({
      next: () => {
        this.session.signIn(key);
        this.router.navigate(['/chat']);
      },
      error: (e) => {
        this.busy.set(false);
        this.error.set(
          e.status === 401 ? 'That key was not accepted.' : 'Could not reach the service.',
        );
      },
    });
  }
}
