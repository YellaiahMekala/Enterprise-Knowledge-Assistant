// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { Component, effect, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ApiService } from './api.service';
import { AUTH_CONFIG } from './auth-config';
import { OidcClient } from './oidc';
import { SessionService } from './session.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <header>
      <strong>Enterprise Knowledge Assistant</strong>
      @if (session.signedIn()) {
        <nav>
          <a routerLink="/chat" routerLinkActive="active">Chat</a>
          <a routerLink="/documents" routerLinkActive="active">Documents</a>
          @if (admin()) {
            <a routerLink="/admin" routerLinkActive="active">Admin</a>
          }
          <button class="link" (click)="signOut()">Sign out</button>
        </nav>
      }
    </header>
    <main><router-outlet /></main>
  `,
})
export class App {
  protected readonly session = inject(SessionService);
  private readonly router = inject(Router);
  private readonly oidc = inject(OidcClient);
  private readonly api = inject(ApiService);
  /** Shows the Admin link; the server still checks the role on every admin call. */
  protected readonly admin = signal(false);

  constructor() {
    // Renew the access token in the background shortly before it expires.
    this.session.keepFresh((token) => this.oidc.refresh(token));
    effect(() => {
      if (!this.session.signedIn()) {
        this.admin.set(false);
        return;
      }
      this.api.me().subscribe({
        next: (me) => this.admin.set(me.role === 'admin'),
        error: () => this.admin.set(false),
      });
    });
  }

  /** Also ends the session at the identity provider, so the next sign-in asks for a password. */
  protected async signOut(): Promise<void> {
    const idToken = this.session.idToken();
    this.session.signOut();
    if (AUTH_CONFIG.mode === 'oidc') {
      const url = await this.oidc.logoutUrl(idToken).catch(() => null);
      if (url) {
        location.assign(url);
        return;
      }
    }
    this.router.navigate(['/login']);
  }
}
