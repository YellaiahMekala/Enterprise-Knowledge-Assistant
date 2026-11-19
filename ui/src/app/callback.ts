// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { Component, OnInit, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import { OidcClient } from './oidc';
import { SessionService } from './session.service';

/** Where the identity provider sends the browser back to after sign-in. */
@Component({
  selector: 'app-callback',
  imports: [RouterLink],
  template: `
    <section class="card narrow">
      @if (error()) {
        <h1>Sign-in failed</h1>
        <p class="error" role="alert">{{ error() }}</p>
        <a routerLink="/login">Back to sign in</a>
      } @else {
        <p class="muted">Signing you in...</p>
      }
    </section>
  `,
})
export class Callback implements OnInit {
  private readonly oidc = inject(OidcClient);
  private readonly session = inject(SessionService);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  protected readonly error = signal('');

  async ngOnInit(): Promise<void> {
    const params = new URLSearchParams(location.search);
    history.replaceState(null, '', '/callback'); // the code is single-use; keep it out of history
    try {
      this.session.signInWithTokens(await this.oidc.complete(params));
      await firstValueFrom(this.api.me()); // the edge accepts the token
      await this.router.navigate(['/chat']);
    } catch (e) {
      this.session.signOut();
      const status = (e as { status?: number }).status;
      this.error.set(
        status === 401 || status === 403
          ? 'The service did not accept this account.'
          : e instanceof Error
            ? e.message
            : 'Could not reach the service.',
      );
    }
  }
}
