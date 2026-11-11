import { SessionService } from './session.service';

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
    session.signInWithTokens({ accessToken: 'at', idToken: 'it', expiresAt: Date.now() + 60_000 });

    expect(session.authHeaders()).toEqual({ Authorization: 'Bearer at' });
    expect(session.idToken()).toBe('it');
  });

  it('treats an expired token as signed out', () => {
    const session = new SessionService();
    session.signInWithTokens({ accessToken: 'at', idToken: null, expiresAt: Date.now() - 1 });

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
});
