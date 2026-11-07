import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
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

  protected signOut(): void {
    this.session.signOut();
    this.router.navigate(['/login']);
  }
}
