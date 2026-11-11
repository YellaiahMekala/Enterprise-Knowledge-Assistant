/**
 * OpenID Connect sign-in for a browser app: authorization code flow with PKCE (RFC 7636), no
 * client secret and no library. The verifier, state and nonce live in sessionStorage only for the
 * round trip to the identity provider. Tokens are kept in sessionStorage by SessionService, so
 * they end with the tab; there is no refresh token handling, the user signs in again after expiry.
 */
import { AuthConfig } from './auth-mode';

export interface OidcEndpoints {
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
}

export interface TokenSet {
  accessToken: string;
  idToken: string | null;
  /** Epoch milliseconds, 30 s before the real expiry so a request does not race it. */
  expiresAt: number;
}

interface Pending {
  verifier: string;
  state: string;
  nonce: string;
}

const PENDING = 'eka.oidc.pending';
const EXPIRY_MARGIN_MS = 30_000;

export function base64Url(bytes: Uint8Array): string {
  let text = '';
  bytes.forEach((b) => (text += String.fromCharCode(b)));
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function randomToken(bytes = 32): string {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return base64Url(buffer);
}

export async function pkceChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

/** The claims of a JWT, without checking its signature (the edge does that). */
export function jwtClaims(token: string): Record<string, unknown> {
  const part = token.split('.')[1] ?? '';
  const base64 = part.replace(/-/g, '+').replace(/_/g, '/');
  const json = new TextDecoder().decode(Uint8Array.from(atob(base64), (c) => c.charCodeAt(0)));
  return JSON.parse(json);
}

export function tokenSet(body: Record<string, unknown>, now: number): TokenSet {
  if (typeof body['access_token'] !== 'string') {
    throw new Error('The sign-in service returned no access token.');
  }
  const expiresIn = typeof body['expires_in'] === 'number' ? body['expires_in'] : 60;
  return {
    accessToken: body['access_token'],
    idToken: typeof body['id_token'] === 'string' ? body['id_token'] : null,
    expiresAt: now + expiresIn * 1000 - EXPIRY_MARGIN_MS,
  };
}

export class OidcClient {
  private endpoints?: Promise<OidcEndpoints>;

  constructor(
    private readonly config: AuthConfig,
    private readonly origin: string = location.origin,
    private readonly http: typeof fetch = (input, init) => fetch(input, init),
    private readonly storage: Storage = sessionStorage,
    private readonly now: () => number = Date.now,
  ) {}

  get redirectUri(): string {
    return `${this.origin}/callback`;
  }

  discover(): Promise<OidcEndpoints> {
    this.endpoints ??= this.http(`${this.config.issuer}/.well-known/openid-configuration`).then(
      (r) => {
        if (!r.ok) throw new Error('The sign-in service could not be reached.');
        return r.json() as Promise<OidcEndpoints>;
      },
    );
    return this.endpoints;
  }

  /** The URL to send the browser to. Remembers what is needed to check the answer. */
  async authorizeUrl(): Promise<string> {
    const endpoints = await this.discover();
    const pending: Pending = {
      verifier: randomToken(48),
      state: randomToken(),
      nonce: randomToken(),
    };
    this.storage.setItem(PENDING, JSON.stringify(pending));
    const query = new URLSearchParams({
      response_type: 'code',
      client_id: this.config.clientId ?? '',
      redirect_uri: this.redirectUri,
      scope: 'openid',
      state: pending.state,
      nonce: pending.nonce,
      code_challenge: await pkceChallenge(pending.verifier),
      code_challenge_method: 'S256',
    });
    return `${endpoints.authorization_endpoint}?${query}`;
  }

  /** Handles the redirect back: checks state, swaps the code for tokens, checks the nonce. */
  async complete(params: URLSearchParams): Promise<TokenSet> {
    const raw = this.storage.getItem(PENDING);
    this.storage.removeItem(PENDING); // one use, whatever happens next
    if (params.get('error')) {
      throw new Error(params.get('error_description') ?? 'Sign-in was cancelled or refused.');
    }
    const pending: Pending | null = raw ? JSON.parse(raw) : null;
    const code = params.get('code');
    if (!pending || !code || params.get('state') !== pending.state) {
      throw new Error('This sign-in response does not belong to this tab. Please sign in again.');
    }
    const endpoints = await this.discover();
    const response = await this.http(endpoints.token_endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: this.redirectUri,
        client_id: this.config.clientId ?? '',
        code_verifier: pending.verifier,
      }),
    });
    if (!response.ok) {
      throw new Error('The sign-in service did not accept the sign-in. Please try again.');
    }
    const tokens = tokenSet(await response.json(), this.now());
    if (tokens.idToken && jwtClaims(tokens.idToken)['nonce'] !== pending.nonce) {
      throw new Error('The sign-in response failed a security check. Please sign in again.');
    }
    return tokens;
  }

  /** Where to send the browser to end the session at the identity provider, if it supports it. */
  async logoutUrl(idToken: string | null): Promise<string | null> {
    const endpoints = await this.discover();
    if (!endpoints.end_session_endpoint) return null;
    const query = new URLSearchParams({
      client_id: this.config.clientId ?? '',
      post_logout_redirect_uri: `${this.origin}/login`,
    });
    if (idToken) query.set('id_token_hint', idToken);
    return `${endpoints.end_session_endpoint}?${query}`;
  }
}
