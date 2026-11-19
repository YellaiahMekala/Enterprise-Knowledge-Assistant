// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class PromQlGuardTest {

    @ParameterizedTest
    @ValueSource(strings = {
        "up",
        "up{job=\"core\"} == 0",
        "sum(rate(eka_http_requests_total{status=~\"5..\"}[5m]))",
        "histogram_quantile(0.95, sum by (le) (rate(eka_http_request_duration_seconds_bucket{route=\"/api/v1/search\"}[5m])))",
        "resilience4j_circuitbreaker_state{name=\"core\",state=\"open\"}",
    })
    void queriesAboutOurOwnMetricsPass(String query) {
        assertThat(PromQlGuard.problem(query)).isNull();
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "   ", "node_cpu_seconds_total", "count({__name__=~\".+\"})"})
    void emptyOrOffTopicQueriesAreRefused(String query) {
        assertThat(PromQlGuard.problem(query)).isNotNull();
    }

    @ParameterizedTest
    @ValueSource(strings = {"up; drop", "up\nup", "up `id`", "up $(id)", "up\\x"})
    void charactersOutsidePlainPromQlAreRefused(String query) {
        assertThat(PromQlGuard.problem(query)).contains("characters");
    }

    @org.junit.jupiter.api.Test
    void longQueriesAreRefused() {
        assertThat(PromQlGuard.problem("up" + " or up".repeat(100))).contains("longer than");
    }

    @org.junit.jupiter.api.Test
    void nullIsRefused() {
        assertThat(PromQlGuard.problem(null)).isNotNull();
    }
}
