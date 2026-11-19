// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.security;

/** Who the caller is, as the core will see them: a pseudonymous id and a role. */
public record Identity(String userId, String role) {

    public static final String USER = "user";
    public static final String ADMIN = "admin";
}
