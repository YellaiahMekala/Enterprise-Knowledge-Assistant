// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.ratelimit;

import java.time.Duration;
import reactor.core.publisher.Mono;

/**
 * Token bucket per user: a burst, then a steady rate. {@link LocalRateLimiter} counts in memory
 * (one edge instance); {@link RedisRateLimiter} counts in Redis, so several instances share one limit.
 */
public interface RateLimiter {

    /** Outcome of one attempt. {@code retryAfter} is only meaningful when not allowed. */
    record Decision(boolean allowed, Duration retryAfter) {

        public static final Decision ALLOW = new Decision(true, Duration.ZERO);
    }

    Mono<Decision> tryAcquire(String userId);
}
