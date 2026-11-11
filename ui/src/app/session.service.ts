import { Injectable, signal } from '@angular/core';
import { TokenSet } from './oidc';

const KEY = 'eka.session';

type Credential =
  | { kind: 'api_key'; key: string }
  | {
      kind: 'bearer';
      accessToken: string;
      idToken: string | null;
      expiresAt: number;
      refreshToken?: string | null;
    };

export type Renew = (refreshToken: string) => Promise<TokenSet>;

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
  private renewing: Promise<void> | null = null;

  signedIn(): boolean {
    const c = this.credential();
    if (c === null) return false;
    return c.kind === 'api_key' || c.expiresAt > Date.now() || !!c.refreshToken;
  }

  /**
   * Swaps an expired access token for a new one before a request. Concurrent callers share one
   * renewal, because the refresh token is single-use. A failed renewal signs out, so the request
   * goes without credentials and its 401 sends the user to the sign-in page.
   */
  fresh(renew: Renew): Promise<void> {
    const c = this.credential();
    if (c?.kind !== 'bearer' || c.expiresAt > Date.now()) return Promise.resolve();
    if (!c.refreshToken) {
      this.signOut();
      return Promise.resolve();
    }
    this.renewing ??= renew(c.refreshToken)
      .then((t) =>
        this.store({
          kind: 'bearer',
          accessToken: t.accessToken,
          idToken: t.idToken ?? c.idToken,
          expiresAt: t.expiresAt,
          refreshToken: t.refreshToken,
        }),
      )
      .catch(() => this.signOut())
      .finally(() => (this.renewing = null));
    return this.renewing;
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
