// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { AuthConfig } from './auth-mode';

/**
 * The default build: an API key pasted by the user, sent as X-API-Key to the core.
 * `ng serve --configuration sso` swaps in auth-config.sso.ts, which signs in through the identity
 * provider and sends a bearer token to the edge (ADR-022).
 */
export const AUTH_CONFIG: AuthConfig = { mode: 'api_key' };
