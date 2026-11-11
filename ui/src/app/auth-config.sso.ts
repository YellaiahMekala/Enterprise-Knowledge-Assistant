import { AuthConfig } from './auth-mode';

// The issuer must match the `iss` claim the edge checks (EKA_EDGE_OIDC_ISSUER). Keycloak in the
// compose file always issues http://keycloak:8180, so the browser needs `127.0.0.1 keycloak` in
// the hosts file.
export const AUTH_CONFIG: AuthConfig = {
  mode: 'oidc',
  issuer: 'http://keycloak:8180/realms/eka',
  clientId: 'eka-ui',
};
