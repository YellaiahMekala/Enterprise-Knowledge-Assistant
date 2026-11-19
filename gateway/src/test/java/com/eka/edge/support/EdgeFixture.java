// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.support;

import java.io.IOException;
import java.net.ServerSocket;
import org.springframework.test.context.DynamicPropertyRegistry;

/**
 * One identity provider, one stub core and two fixed ports for the whole test run, so every
 * Spring test shares a single application context.
 */
public final class EdgeFixture {

    public static final TestIdp IDP = new TestIdp();
    public static final StubCore CORE = new StubCore();
    public static final int EDGE_PORT = freePort();
    public static final int MANAGEMENT_PORT = freePort();
    public static final String PSEUDONYM_SECRET = "test-only-pseudonym-secret-0123456789";

    private EdgeFixture() {}

    public static void register(DynamicPropertyRegistry registry) {
        registry.add("server.port", () -> EDGE_PORT);
        registry.add("management.server.port", () -> MANAGEMENT_PORT);
        registry.add("eka.edge.core-url", CORE::url);
        registry.add("spring.cloud.gateway.server.webflux.httpclient.response-timeout", () -> "2s");
        registry.add("eka.edge.pseudonym-secret", () -> PSEUDONYM_SECRET);
        registry.add("eka.edge.oidc.issuer", () -> TestIdp.ISSUER);
        registry.add("eka.edge.oidc.jwk-set-uri", IDP::jwkSetUri);
        registry.add("eka.edge.oidc.audience", () -> TestIdp.AUDIENCE);
        registry.add("eka.edge.internal-token.ephemeral-key", () -> "true");
    }

    public static String edge(String path) {
        return "http://127.0.0.1:" + EDGE_PORT + path;
    }

    public static String management(String path) {
        return "http://127.0.0.1:" + MANAGEMENT_PORT + path;
    }

    private static int freePort() {
        try (ServerSocket socket = new ServerSocket(0)) {
            return socket.getLocalPort();
        } catch (IOException e) {
            throw new IllegalStateException(e);
        }
    }
}
