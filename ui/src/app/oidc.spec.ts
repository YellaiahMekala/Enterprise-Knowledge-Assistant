import { OidcClient, base64Url, jwtClaims, pkceChallenge, tokenSet } from './oidc';

const ISSUER = 'http://keycloak:8180/realms/eka';
const ENDPOINTS = {
  authorization_endpoint: `${ISSUER}/protocol/openid-connect/auth`,
  token_endpoint: `${ISSUER}/protocol/openid-connect/token`,
  end_session_endpoint: `${ISSUER}/protocol/openid-connect/logout`,
};

class MemoryStorage implements Storage {
  private items = new Map<string, string>();
  get length() {
    return this.items.size;
  }
  clear() {
    this.items.clear();
  }
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  key(index: number) {
    return [...this.items.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.items.delete(key);
  }
  setItem(key: string, value: string) {
    this.items.set(key, value);
  }
}

function jwt(claims: object): string {
  const part = (o: object) => base64Url(new TextEncoder().encode(JSON.stringify(o)));
  return `${part({ alg: 'RS256' })}.${part(claims)}.sig`;
}

function json(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function setup(tokenReply?: (body: URLSearchParams) => Response) {
  const calls: { url: string; body?: URLSearchParams }[] = [];
  const http = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body instanceof URLSearchParams ? init.body : undefined;
    calls.push({ url, body });
    if (url.endsWith('/.well-known/openid-configuration')) return json(ENDPOINTS);
    if (url === ENDPOINTS.token_endpoint && tokenReply && body) return tokenReply(body);
    return json({}, 404);
  }) as typeof fetch;
  const storage = new MemoryStorage();
  const client = new OidcClient(
    { mode: 'oidc', issuer: ISSUER, clientId: 'eka-ui' },
    'http://localhost:4200',
    http,
    storage,
    () => 1_000_000,
  );
  return { client, calls, storage };
}

async function startedSignIn(client: OidcClient) {
  const url = new URL(await client.authorizeUrl());
  return { state: url.searchParams.get('state')!, nonce: url.searchParams.get('nonce')! };
}

describe('PKCE', () => {
  it('matches the RFC 7636 example', async () => {
    expect(await pkceChallenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk')).toBe(
      'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
    );
  });
});

describe('OidcClient', () => {
  it('builds an authorization code request with PKCE, state and nonce', async () => {
    const { client, storage } = setup();

    const url = new URL(await client.authorizeUrl());

    expect(`${url.origin}${url.pathname}`).toBe(ENDPOINTS.authorization_endpoint);
    const q = url.searchParams;
    expect(q.get('response_type')).toBe('code');
    expect(q.get('client_id')).toBe('eka-ui');
    expect(q.get('redirect_uri')).toBe('http://localhost:4200/callback');
    expect(q.get('scope')).toBe('openid');
    expect(q.get('code_challenge_method')).toBe('S256');
    const pending = JSON.parse(storage.getItem('eka.oidc.pending')!);
    expect(q.get('state')).toBe(pending.state);
    expect(q.get('code_challenge')).toBe(await pkceChallenge(pending.verifier));
    expect(url.toString()).not.toContain(pending.verifier);
  });

  it('swaps the code for tokens with the verifier and checks the nonce', async () => {
    let sent: URLSearchParams | undefined;
    let nonce = '';
    const { client, storage } = setup((body) => {
      sent = body;
      return json({ access_token: 'access', id_token: jwt({ nonce }), expires_in: 300 });
    });
    const started = await startedSignIn(client);
    nonce = started.nonce;
    const verifier = JSON.parse(storage.getItem('eka.oidc.pending')!).verifier;

    const tokens = await client.complete(new URLSearchParams({ code: 'c1', state: started.state }));

    expect(tokens.accessToken).toBe('access');
    expect(tokens.expiresAt).toBe(1_000_000 + 300_000 - 30_000);
    expect(sent?.get('grant_type')).toBe('authorization_code');
    expect(sent?.get('code')).toBe('c1');
    expect(sent?.get('code_verifier')).toBe(verifier);
    expect(sent?.get('redirect_uri')).toBe('http://localhost:4200/callback');
    expect(storage.getItem('eka.oidc.pending')).toBeNull();
  });

  it('refuses a response whose state does not match, without calling the token endpoint', async () => {
    const { client, calls } = setup(() => json({ access_token: 'x' }));
    await startedSignIn(client);

    await expect(
      client.complete(new URLSearchParams({ code: 'c1', state: 'forged' })),
    ).rejects.toThrow('does not belong to this tab');
    expect(calls.some((c) => c.url === ENDPOINTS.token_endpoint)).toBe(false);
  });

  it('refuses a replayed response: the pending sign-in is used once', async () => {
    const { client } = setup(() => json({ access_token: 'x' }));
    const { state } = await startedSignIn(client);
    await client.complete(new URLSearchParams({ code: 'c1', state }));

    await expect(client.complete(new URLSearchParams({ code: 'c1', state }))).rejects.toThrow();
  });

  it('swaps a refresh token for new tokens, keeping the rotated refresh token', async () => {
    let sent: URLSearchParams | undefined;
    const { client } = setup((body) => {
      sent = body;
      return json({ access_token: 'a2', refresh_token: 'r2', expires_in: 300 });
    });

    const tokens = await client.refresh('r1');

    expect(sent?.get('grant_type')).toBe('refresh_token');
    expect(sent?.get('refresh_token')).toBe('r1');
    expect(sent?.get('client_id')).toBe('eka-ui');
    expect(tokens).toEqual({
      accessToken: 'a2',
      idToken: null,
      expiresAt: 1_000_000 + 300_000 - 30_000,
      refreshToken: 'r2',
    });
  });

  it('reports an ended session when the refresh is refused', async () => {
    const { client } = setup(() => json({ error: 'invalid_grant' }, 400));

    await expect(client.refresh('old')).rejects.toThrow('session has ended');
  });

  it('refuses an id token with another nonce', async () => {
    const { client } = setup(() => json({ access_token: 'x', id_token: jwt({ nonce: 'other' }) }));
    const { state } = await startedSignIn(client);

    await expect(client.complete(new URLSearchParams({ code: 'c1', state }))).rejects.toThrow(
      'security check',
    );
  });

  it('reports an error sent back by the identity provider', async () => {
    const { client } = setup();
    await startedSignIn(client);

    await expect(
      client.complete(
        new URLSearchParams({ error: 'access_denied', error_description: 'User cancelled' }),
      ),
    ).rejects.toThrow('User cancelled');
  });

  it('reports a refused token exchange', async () => {
    const { client } = setup(() => json({ error: 'invalid_grant' }, 400));
    const { state } = await startedSignIn(client);

    await expect(client.complete(new URLSearchParams({ code: 'c1', state }))).rejects.toThrow(
      'did not accept',
    );
  });

  it('builds a logout URL that returns to the login page', async () => {
    const { client } = setup();

    const url = new URL((await client.logoutUrl('id-token'))!);

    expect(url.searchParams.get('post_logout_redirect_uri')).toBe('http://localhost:4200/login');
    expect(url.searchParams.get('id_token_hint')).toBe('id-token');
  });
});

describe('token helpers', () => {
  it('reads JWT claims', () => {
    expect(jwtClaims(jwt({ nonce: 'n', sub: 'alice' }))).toEqual({ nonce: 'n', sub: 'alice' });
  });

  it('rejects a reply without an access token', () => {
    expect(() => tokenSet({ id_token: 'x' }, 0)).toThrow('no access token');
  });
});
