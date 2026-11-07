package com.eka.edge.ratelimit;

import com.eka.edge.config.EdgeProperties;
import java.time.Clock;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

/**
 * Token bucket per user. In memory, so each edge instance counts on its own; with N instances
 * the effective limit is up to N times the configured one.
 */
@Component
public class RateLimiter {

    /** Outcome of one attempt. {@code retryAfter} is only meaningful when not allowed. */
    public record Decision(boolean allowed, Duration retryAfter) {}

    private static final Duration IDLE_EVICTION = Duration.ofMinutes(10);

    private final EdgeProperties.RateLimit limit;
    private final Clock clock;
    private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();

    public RateLimiter(EdgeProperties properties, Clock clock) {
        this.limit = properties.rateLimit();
        this.clock = clock;
    }

    public Decision tryAcquire(String userId) {
        long now = clock.millis();
        evictIdle(now);
        Bucket bucket = buckets.computeIfAbsent(userId, id -> new Bucket(limit.burst(), now));
        synchronized (bucket) {
            double refilled = (now - bucket.updatedAt) / 1000.0 * limit.perSecond();
            bucket.tokens = Math.min(limit.burst(), bucket.tokens + refilled);
            bucket.updatedAt = now;
            if (bucket.tokens >= 1) {
                bucket.tokens -= 1;
                return new Decision(true, Duration.ZERO);
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
