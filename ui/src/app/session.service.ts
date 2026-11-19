// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
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

/** Renew this long before the access token's expiry time (which is already 30 s before the real one). */
export const RENEW_LEAD_MS = 60_000;
const MAX_TIMER_MS = 2_147_483_647;

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
  private renew: Renew | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

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
    return this.renewNow(c, renew);
  }

  /**
   * Renews in the background shortly before the access token expires, so a long-open page never
   * sends an expired token. Uses the same single shared renewal as fresh(). A tab that was asleep
   * past the renewal time renews when it becomes visible again.
   */
  keepFresh(renew: Renew): void {
    this.renew = renew;
    this.schedule();
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') this.schedule();
    });
  }

  private renewNow(c: Credential & { kind: 'bearer' }, renew: Renew): Promise<void> {
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

  /** One timer for the current token; every store or sign-out replaces it. */
  private schedule(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    const c = this.credential();
    if (this.renew === null || c?.kind !== 'bearer' || !c.refreshToken) return;
    const renew = this.renew;
    const wait = Math.min(Math.max(c.expiresAt - RENEW_LEAD_MS - Date.now(), 0), MAX_TIMER_MS);
    this.timer = setTimeout(() => {
      this.timer = null;
      const now = this.credential();
      if (now?.kind !== 'bearer') return;
      // A clamped wait may fire early; then look again instead of renewing a young token.
      if (now.expiresAt - RENEW_LEAD_MS > Date.now()) this.schedule();
      else void this.renewNow(now, renew);
    }, wait);
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
    this.schedule();
  }

  private store(credential: Credential): void {
    sessionStorage.setItem(KEY, JSON.stringify(credential));
    this.credential.set(credential);
    this.schedule();
  }
}
