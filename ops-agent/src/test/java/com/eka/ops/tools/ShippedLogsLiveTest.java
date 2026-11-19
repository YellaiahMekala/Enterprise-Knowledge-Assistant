// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * The agent's CloudWatch search over logs the local shipper wrote (ADR-040): compose profile
 * "cloudwatch" (log-shipper and localstack) running with some core traffic, then
 * EKA_LIVE_SHIPPED_LOG_GROUP=/eka-local and EKA_LIVE_CLOUDWATCH_ENDPOINT=http://127.0.0.1:4566
 * plus any AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_REGION. Skipped otherwise.
 */
@EnabledIfEnvironmentVariable(named = "EKA_LIVE_SHIPPED_LOG_GROUP", matches = ".+")
class ShippedLogsLiveTest {

    private final LogSearch search = new LogSearch(CloudWatchLogStore.connect(
            System.getenv("EKA_LIVE_SHIPPED_LOG_GROUP"),
            System.getenv("EKA_LIVE_CLOUDWATCH_ENDPOINT"),
            Duration.ofSeconds(10)));

    @Test
    void theCoresShippedLinesAreFoundUnderItsAwsStreamName() {
        String result = search.search("api", "", 15);

        assertThat(result).contains("eka/core/*").doesNotContain("no log lines");
        assertThat(result).containsPattern("GET /health/ready|/api/v1/documents");
    }

    @Test
    void aLevelWordFindsTheWarningsTheCoreLogged() {
        String result = search.search("api", "ERROR", 15);

        assertThat(result).contains("pattern ?\"ERROR\"").containsPattern("WARNING|ERROR");
    }
}
