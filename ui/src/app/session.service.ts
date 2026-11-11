import { Injectable, signal } from '@angular/core';
import { TokenSet } from './oidc';

const KEY = 'eka.session';

type Credential =
  | { kind: 'api_key'; key: string }
  | { kind: 'bearer'; accessToken: string; idToken: string | null; expiresAt: number };

function load(): Credential | null {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? 'null');
  } catch {
    return null;
  }
}

/** What the browser tab signs requests with. Kept in sessionStorage, so it ends with the tab. */
@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly credential = signal<Credential | null>(load());

  signedIn(): boolean {
    const c = this.credential();
    return c !== null && (c.kind === 'api_key' || c.expiresAt > Date.now());
  }

  /** Headers for a call to the API: X-API-Key for the core, a bearer token for the edge. */
  authHeaders(): Record<string, string> {
    const c = this.credential();
    if (c === null) return {};
    return c.kind === 'api_key'
      ? { 'X-API-Key': c.key }
      : { Authorization: `Bearer ${c.accessToken}` };
  }

  idToken(): string | null {
    const c = this.credential();
    return c?.kind === 'bearer' ? c.idToken : null;
  }

  signIn(apiKey: string): void {
    this.store({ kind: 'api_key', key: apiKey });
  }

  signInWithTokens(tokens: TokenSet): void {
    this.store({ kind: 'bearer', ...tokens });
  }

  signOut(): void {
    sessionStorage.removeItem(KEY);
    this.credential.set(null);
  }

  private store(credential: Credential): void {
    sessionStorage.setItem(KEY, JSON.stringify(credential));
    this.credential.set(credential);
  }
}
