// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { AuthConfig } from './auth-mode';

// The issuer must match the `iss` claim the edge checks (EKA_EDGE_OIDC_ISSUER). Keycloak in the
// compose file always issues http://keycloak:8180, so the browser needs `127.0.0.1 keycloak` in
// the hosts file.
export const AUTH_CONFIG: AuthConfig = {
  mode: 'oidc',
  issuer: 'http://keycloak:8180/realms/eka',
  clientId: 'eka-ui',
};
