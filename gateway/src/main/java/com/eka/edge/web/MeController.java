// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.web;

import com.eka.edge.security.Identity;
import com.eka.edge.security.IdentityMapper;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Answered by the edge itself: who the core will think you are. Same shape as the core's
 * {@code GET /api/v1/me}, so a client does not care which service replies.
 */
@RestController
class MeController {

    private final IdentityMapper identities;

    MeController(IdentityMapper identities) {
        this.identities = identities;
    }

    @GetMapping("/api/v1/me")
    Me me(@AuthenticationPrincipal Jwt jwt) {
        Identity identity = identities.from(jwt);
        return new Me(identity.userId(), identity.role());
    }

    record Me(String user_id, String role) {}
}
