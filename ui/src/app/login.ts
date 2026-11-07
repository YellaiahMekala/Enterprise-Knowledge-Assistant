import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from './api.service';
import { SessionService } from './session.service';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  template: `
    <section class="card narrow">
      <h1>Sign in</h1>
      <p class="muted">Paste your API key. It is kept for this browser tab only.</p>
      <form (ngSubmit)="submit()">
        <input type="password" name="key" [ngModel]="key()" (ngModelChange)="key.set($event)" placeholder="API key" autocomplete="off" required />
        <button type="submit" [disabled]="busy() || !key()">Continue</button>
      </form>
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

  protected readonly key = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  protected submit(): void {
    this.busy.set(true);
    this.error.set('');
    this.session.signIn(this.key().trim());
    this.api.me().subscribe({
      next: () => this.router.navigate(['/chat']),
      error: (e) => {
        this.busy.set(false);
        // The interceptor already cleared the key on a 401.
        this.error.set(e.status === 401 ? 'That key was not accepted.' : 'Could not reach the service.');
        if (e.status !== 401) this.session.signOut();
      },
    });
  }
}
