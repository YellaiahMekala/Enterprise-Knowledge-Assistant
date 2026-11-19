// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.edge.support.EdgeFixture;
import com.eka.edge.support.EdgeTestBase;
import com.eka.edge.support.Http;
import com.eka.edge.support.TestIdp;
import org.junit.jupiter.api.Test;

class ManagementEndpointsTest extends EdgeTestBase {

    @Test
    void prometheusMetricsAreServedOnTheManagementPortOnly() {
        String token = EdgeFixture.IDP.sign(TestIdp.validClaims("metrics-user").build());
        Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token));

        var metrics = Http.get(EdgeFixture.management("/actuator/prometheus"));
        assertThat(metrics.statusCode()).isEqualTo(200);
        assertThat(metrics.body()).contains("jvm_memory_used_bytes");

        var publicPort = Http.get(EdgeFixture.edge("/actuator/prometheus"));
        assertThat(publicPort.statusCode()).isIn(401, 404);
    }

    @Test
    void metricsDoNotCarryUserIdentifiers() {
        String token = EdgeFixture.IDP.sign(TestIdp.validClaims("secret-subject-123").build());
        Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token));

        String body = Http.get(EdgeFixture.management("/actuator/prometheus")).body();
        assertThat(body).doesNotContain("secret-subject-123").doesNotContain("Bearer");
    }
}
