// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.ratelimit;

import com.eka.edge.config.EdgeProperties;
import java.time.Clock;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import reactor.core.publisher.Mono;

/**
 * Token bucket per user, in memory, so each edge instance counts on its own; with N instances
 * the effective limit is up to N times the configured one. Used when no Redis URL is set.
 */
public class LocalRateLimiter implements RateLimiter {

    private static final Duration IDLE_EVICTION = Duration.ofMinutes(10);

    private final EdgeProperties.RateLimit limit;
    private final Clock clock;
    private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();

    public LocalRateLimiter(EdgeProperties.RateLimit limit, Clock clock) {
        this.limit = limit;
        this.clock = clock;
    }

    @Override
    public Mono<Decision> tryAcquire(String userId) {
        return Mono.just(acquire(userId));
    }

    Decision acquire(String userId) {
        long now = clock.millis();
        evictIdle(now);
        Bucket bucket = buckets.computeIfAbsent(userId, id -> new Bucket(limit.burst(), now));
        synchronized (bucket) {
            double refilled = (now - bucket.updatedAt) / 1000.0 * limit.perSecond();
            bucket.tokens = Math.min(limit.burst(), bucket.tokens + refilled);
            bucket.updatedAt = now;
            if (bucket.tokens >= 1) {
                bucket.tokens -= 1;
                return Decision.ALLOW;
            }
            long waitMillis = (long) Math.ceil((1 - bucket.tokens) / limit.perSecond() * 1000);
            return new Decision(false, Duration.ofMillis(waitMillis));
        }
    }

    private void evictIdle(long now) {
        if (buckets.size() < 1024) {
            return;
        }
        long cutoff = now - IDLE_EVICTION.toMillis();
        buckets.values().removeIf(bucket -> bucket.updatedAt < cutoff);
    }

    private static final class Bucket {
        double tokens;
        long updatedAt;

        Bucket(double tokens, long updatedAt) {
            this.tokens = tokens;
            this.updatedAt = updatedAt;
        }
    }
}
