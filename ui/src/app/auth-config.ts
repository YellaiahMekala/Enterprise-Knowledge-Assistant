import { AuthConfig } from './auth-mode';

/**
 * The default build: an API key pasted by the user, sent as X-API-Key to the core.
 * `ng serve --configuration sso` swaps in auth-config.sso.ts, which signs in through the identity
 * provider and sends a bearer token to the edge (ADR-022).
 */
export const AUTH_CONFIG: AuthConfig = { mode: 'api_key' };
