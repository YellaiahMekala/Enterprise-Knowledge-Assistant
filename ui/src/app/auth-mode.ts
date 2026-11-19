// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
/** How the UI signs people in; the values live in auth-config.ts (swapped per build). */
export interface AuthConfig {
  mode: 'api_key' | 'oidc';
  /** OIDC issuer URL, without a trailing slash (oidc mode only). */
  issuer?: string;
  /** Public client registered at the identity provider (oidc mode only). */
  clientId?: string;
}
