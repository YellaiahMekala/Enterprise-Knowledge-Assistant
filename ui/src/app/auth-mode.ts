/** How the UI signs people in; the values live in auth-config.ts (swapped per build). */
export interface AuthConfig {
  mode: 'api_key' | 'oidc';
  /** OIDC issuer URL, without a trailing slash (oidc mode only). */
  issuer?: string;
  /** Public client registered at the identity provider (oidc mode only). */
  clientId?: string;
}
