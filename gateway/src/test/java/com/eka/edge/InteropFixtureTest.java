// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.edge.support.EdgeFixture;
import com.eka.edge.support.EdgeTestBase;
import com.eka.edge.support.Http;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import com.eka.edge.token.InternalTokenService;

/**
 * Writes a token minted by the edge and its published key set to target/interop, where the
 * Python core's interop test picks them up.
 */
class InteropFixtureTest extends EdgeTestBase {

    @Autowired
    InternalTokenService tokens;

    @Test
    void writesTokenAndKeySetForTheCore() throws Exception {
        Path dir = Path.of("target", "interop");
        Files.createDirectories(dir);

        String user = tokens.mint("u0123456789abcdef0123456789abcdef", "user", "interop-1");
        String admin = tokens.mint("uffffffffffffffffffffffffffffffff", "admin", "interop-2");
        var jwks = Http.get(EdgeFixture.management("/actuator/jwks"));

        assertThat(jwks.statusCode()).isEqualTo(200);
        Files.writeString(dir.resolve("user.jwt"), user);
        Files.writeString(dir.resolve("admin.jwt"), admin);
        Files.writeString(dir.resolve("jwks.json"), jwks.body());
    }
}
