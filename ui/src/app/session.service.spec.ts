import { TokenSet } from './oidc';
import { SessionService } from './session.service';

function tokens(overrides: Partial<TokenSet> = {}): TokenSet {
  return {
    accessToken: 'at',
    idToken: null,
    expiresAt: Date.now() + 60_000,
    refreshToken: 'rt',
    ...overrides,
  };
}

describe('SessionService', () => {
  beforeEach(() => sessionStorage.clear());

  it('sends an API key as X-API-Key', () => {
    const session = new SessionService();
    session.signIn('k1');

    expect(session.signedIn()).toBe(true);
    expect(session.authHeaders()).toEqual({ 'X-API-Key': 'k1' });
  });

  it('sends a token as a bearer header and keeps the id token for sign-out', () => {
    const session = new SessionService();
    session.signInWithTokens(tokens({ idToken: 'it' }));

    expect(session.authHeaders()).toEqual({ Authorization: 'Bearer at' });
    expect(session.idToken()).toBe('it');
  });

  it('treats an expired token as signed out', () => {
    const session = new SessionService();
    session.signInWithTokens(tokens({ expiresAt: Date.now() - 1, refreshToken: null }));

    expect(session.signedIn()).toBe(false);
  });

  it('survives a reload of the tab and forgets everything on sign-out', () => {
    new SessionService().signIn('k1');
    const reloaded = new SessionService();
    expect(reloaded.authHeaders()).toEqual({ 'X-API-Key': 'k1' });

    reloaded.signOut();

    expect(new SessionService().signedIn()).toBe(false);
    expect(reloaded.authHeaders()).toEqual({});
  });

  it('does not renew a token that is still valid', async () => {
    const session = new SessionService();
    session.signInWithTokens(tokens());
    const renew = vi.fn();

    await session.fresh(renew);

    expect(renew).not.toHaveBeenCalled();
    expect(session.authHeaders()).toEqual({ Authorization: 'Bearer at' });
  });

  it('renews an expired token once for concurrent requests and stores the rotated token', async () => {
    const session = new SessionService();
    session.signInWithTokens(tokens({ idToken: 'it', expiresAt: Date.now() - 1 }));
    expect(session.signedIn()).toBe(true); // the refresh token still counts
    const renew = vi.fn(async (refreshToken: string) =>
      tokens({ accessToken: `new-for-${refreshToken}`, idToken: null, refreshToken: 'rt2' }),
    );

    await Promise.all([session.fresh(renew), session.fresh(renew), session.fresh(renew)]);

    expect(renew).toHaveBeenCalledTimes(1);
    expect(session.authHeaders()).toEqual({ Authorization: 'Bearer new-for-rt' });
    expect(session.idToken()).toBe('it'); // kept for sign-out when the reply has none
    expect(JSON.parse(sessionStorage.getItem('eka.session')!).refreshToken).toBe('rt2');
  });

  it('signs out when the renewal fails', async () => {
    const session = new SessionService();
    session.signInWithTokens(tokens({ expiresAt: Date.now() - 1 }));

    await session.fresh(async () => {
      throw new Error('session has ended');
    });

    expect(session.signedIn()).toBe(false);
    expect(session.authHeaders()).toEqual({});
  });

  it('leaves an API key alone', async () => {
    const session = new SessionService();
    session.signIn('k1');
    const renew = vi.fn();

    await session.fresh(renew);

    expect(renew).not.toHaveBeenCalled();
    expect(session.authHeaders()).toEqual({ 'X-API-Key': 'k1' });
  });

  describe('renewal before expiry', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('renews in the background one lead time before the token expires', async () => {
      const session = new SessionService();
      session.signInWithTokens(tokens({ expiresAt: Date.now() + 5 * 60_000 }));
      const renew = vi.fn(async () =>
        tokens({ accessToken: 'at2', refreshToken: 'rt2', expiresAt: Date.now() + 5 * 60_000 }),
      );
      session.keepFresh(renew);

      await vi.advanceTimersByTimeAsync(4 * 60_000 - 1);
      expect(renew).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(2);

      expect(renew).toHaveBeenCalledTimes(1);
      expect(renew).toHaveBeenCalledWith('rt');
      expect(session.authHeaders()).toEqual({ Authorization: 'Bearer at2' });
    });

    it('schedules the next renewal for the new token', async () => {
      const session = new SessionService();
      session.signInWithTokens(tokens({ expiresAt: Date.now() + 2 * 60_000 }));
      let n = 0;
      const renew = vi.fn(async () =>
        tokens({ accessToken: `at${++n}`, refreshToken: `rt${n}`, expiresAt: Date.now() + 2 * 60_000 }),
      );
      session.keepFresh(renew);

      await vi.advanceTimersByTimeAsync(3 * 60_000);

      expect(renew).toHaveBeenCalledTimes(3);
      expect(renew).toHaveBeenLastCalledWith('rt2');
    });

    it('renews at once when the token is already inside the lead time', async () => {
      const session = new SessionService();
      session.signInWithTokens(tokens({ expiresAt: Date.now() + 10_000 }));
      const renew = vi.fn(async () => tokens({ accessToken: 'at2', expiresAt: Date.now() + 5 * 60_000 }));

      session.keepFresh(renew);
      await vi.advanceTimersByTimeAsync(0);

      expect(renew).toHaveBeenCalledTimes(1);
    });

    it('shares one renewal with a request that arrives at the same moment', async () => {
      const session = new SessionService();
      session.signInWithTokens(tokens({ expiresAt: Date.now() + 10_000 }));
      const renew = vi.fn(async () => tokens({ accessToken: 'at2', expiresAt: Date.now() + 5 * 60_000 }));
      session.keepFresh(renew);

      await vi.advanceTimersByTimeAsync(0);
      await session.fresh(renew); // still valid after the renewal, so no second call

      expect(renew).toHaveBeenCalledTimes(1);
    });

    it('stops on sign-out and never renews an API key', async () => {
      const session = new SessionService();
      session.signInWithTokens(tokens({ expiresAt: Date.now() + 5 * 60_000 }));
      const renew = vi.fn(async () => tokens());
      session.keepFresh(renew);

      session.signOut();
      await vi.advanceTimersByTimeAsync(10 * 60_000);
      session.signIn('k1');
      await vi.advanceTimersByTimeAsync(10 * 60_000);

      expect(renew).not.toHaveBeenCalled();
    });

    it('signs out when the background renewal fails', async () => {
      const session = new SessionService();
      session.signInWithTokens(tokens({ expiresAt: Date.now() + 90_000 }));
      session.keepFresh(async () => {
        throw new Error('session has ended');
      });

      await vi.advanceTimersByTimeAsync(60_000);

      expect(session.signedIn()).toBe(false);
    });

    it('looks again after a clamped timer instead of renewing a young token', async () => {
      const session = new SessionService();
      const day = 24 * 3600_000;
      session.signInWithTokens(tokens({ expiresAt: Date.now() + 40 * day }));
      const renew = vi.fn(async () => tokens());
      session.keepFresh(renew);

      await vi.advanceTimersByTimeAsync(25 * day);

      expect(renew).not.toHaveBeenCalled();
    });
  });
});
