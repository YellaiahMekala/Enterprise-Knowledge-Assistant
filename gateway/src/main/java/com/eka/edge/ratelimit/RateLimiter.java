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
