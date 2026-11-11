import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
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
