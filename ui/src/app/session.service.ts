import { Injectable, computed, signal } from '@angular/core';

const KEY = 'eka.apiKey';

@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly key = signal<string | null>(sessionStorage.getItem(KEY));
  readonly signedIn = computed(() => this.key() !== null);

  apiKey(): string | null {
    return this.key();
  }

  signIn(apiKey: string): void {
    sessionStorage.setItem(KEY, apiKey);
    this.key.set(apiKey);
  }

  signOut(): void {
    sessionStorage.removeItem(KEY);
    this.key.set(null);
  }
}
