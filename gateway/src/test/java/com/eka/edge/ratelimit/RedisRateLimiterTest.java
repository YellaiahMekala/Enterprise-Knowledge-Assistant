// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.ratelimit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import com.eka.edge.config.EdgeProperties;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

/**
 * The shared limiter against a real Redis, named by EKA_TEST_REDIS_URL (CI starts one); skipped
 * without it. The fail-open test needs no Redis.
 */
class RedisRateLimiterTest {

    private static final String URL = System.getenv("EKA_TEST_REDIS_URL");
    private static final Duration TIMEOUT = Duration.ofSeconds(2);

    // A burst of 5 and almost no refill, so the count is exact during the test.
    private static EdgeProperties.RateLimit limit() {
        return new EdgeProperties.RateLimit(5, 0.01, null, TIMEOUT);
    }

    @Test
    void twoEdgeInstancesShareOneBucketPerUser() {
        assumeTrue(URL != null && !URL.isBlank(), "EKA_TEST_REDIS_URL not set");
        String user = "u-" + UUID.randomUUID();
        try (var a = new RedisRateLimiter(URL, limit(), TIMEOUT);
                var b = new RedisRateLimiter(URL, limit(), TIMEOUT)) {
            List<RateLimiter.Decision> decisions = new ArrayList<>();
            for (int i = 0; i < 10; i++) {
                decisions.add((i % 2 == 0 ? a : b).tryAcquire(user).block());
            }

            // In memory each instance would allow 5, so 10 in total; shared, it is 5.
            assertThat(decisions).filteredOn(RateLimiter.Decision::allowed).hasSize(5);
            assertThat(decisions.subList(5, 10)).allSatisfy(d -> {
                assertThat(d.allowed()).isFalse();
                assertThat(d.retryAfter()).isPositive();
            });
        }
    }

    @Test
    void oneUsersBurstDoesNotSpendAnothersBucket() {
        assumeTrue(URL != null && !URL.isBlank(), "EKA_TEST_REDIS_URL not set");
        try (var limiter = new RedisRateLimiter(URL, limit(), TIMEOUT)) {
            String hog = "hog-" + UUID.randomUUID();
            for (int i = 0; i < 8; i++) {
                limiter.tryAcquire(hog).block();
            }

            assertThat(limiter.tryAcquire(hog).block().allowed()).isFalse();
            assertThat(limiter.tryAcquire("bystander-" + UUID.randomUUID()).block().allowed()).isTrue();
        }
    }

    @Test
    void anUnreachableRedisLetsTheRequestThrough() {
        Duration shortTimeout = Duration.ofMillis(300);
        try (var limiter = new RedisRateLimiter(
                "redis://127.0.0.1:1", new EdgeProperties.RateLimit(1, 0.01, null, shortTimeout), shortTimeout)) {
            for (int i = 0; i < 3; i++) {
                assertThat(limiter.tryAcquire("anyone").block()).isEqualTo(RateLimiter.Decision.ALLOW);
            }
        }
    }

    @Test
    void theScriptReplyBecomesADecision() {
        assertThat(RedisRateLimiter.decision(List.of(1L, 0L))).isEqualTo(RateLimiter.Decision.ALLOW);
        assertThat(RedisRateLimiter.decision(List.of(0L, 1500L)))
                .isEqualTo(new RateLimiter.Decision(false, Duration.ofMillis(1500)));
    }
}
