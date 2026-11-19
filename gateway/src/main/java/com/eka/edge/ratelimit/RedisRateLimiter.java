// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.ratelimit;

import com.eka.edge.config.EdgeProperties;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.codec.StringCodec;
import java.time.Duration;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.publisher.Mono;

/**
 * The same token bucket, kept in Redis so every edge instance draws from one bucket per user.
 * One Lua script reads, refills and takes a token atomically, using the Redis clock so instances
 * with drifting clocks agree.
 *
 * <p>If Redis is slow or down the request is allowed (fail open) and a warning is logged: losing
 * the limit for a while is better than refusing every user. The WAF's per-address rate rule still
 * applies in front.
 */
public class RedisRateLimiter implements RateLimiter, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(RedisRateLimiter.class);

    static final String KEY_PREFIX = "eka:ratelimit:";

    // KEYS[1] bucket; ARGV[1] burst; ARGV[2] tokens per second. Returns {allowed 0|1, wait ms}.
    static final String SCRIPT = """
            local t = redis.call('TIME')
            local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
            local burst = tonumber(ARGV[1])
            local rate = tonumber(ARGV[2])
            local saved = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
            local tokens = tonumber(saved[1]) or burst
            local ts = tonumber(saved[2]) or now
            tokens = math.min(burst, tokens + math.max(0, now - ts) / 1000 * rate)
            local allowed = 0
            local wait = 0
            if tokens >= 1 then
              tokens = tokens - 1
              allowed = 1
            else
              wait = math.ceil((1 - tokens) / rate * 1000)
            end
            redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', now)
            redis.call('PEXPIRE', KEYS[1], math.ceil(burst / rate * 1000) + 1000)
            return {allowed, wait}
            """;

    private final RedisClient client;
    private final RedisURI uri;
    private final EdgeProperties.RateLimit limit;
    private final Duration timeout;
    private volatile StatefulRedisConnection<String, String> connection;

    public RedisRateLimiter(String url, EdgeProperties.RateLimit limit, Duration timeout) {
        this.uri = RedisURI.create(url);
        this.uri.setTimeout(timeout);
        this.client = RedisClient.create();
        this.limit = limit;
        this.timeout = timeout;
    }

    @Override
    public Mono<Decision> tryAcquire(String userId) {
        return connect()
                .flatMap(c -> c.reactive()
                        .eval(SCRIPT, ScriptOutputType.MULTI, new String[] {KEY_PREFIX + userId},
                                Integer.toString(limit.burst()), Double.toString(limit.perSecond()))
                        .next())
                .map(RedisRateLimiter::decision)
                .timeout(timeout)
                .onErrorResume(e -> {
                    log.warn("rate limit check failed, request allowed: {}: {}",
                            e.getClass().getSimpleName(), e.getMessage());
                    return Mono.just(Decision.ALLOW);
                });
    }

    /** The MULTI reply arrives as one element holding the script's list {allowed, wait}. */
    static Decision decision(Object element) {
        List<?> reply = (List<?>) element;
        boolean allowed = ((Number) reply.get(0)).longValue() == 1;
        long waitMillis = ((Number) reply.get(1)).longValue();
        return allowed ? Decision.ALLOW : new Decision(false, Duration.ofMillis(waitMillis));
    }

    /** Connects on first use, and again after a failed connect; Lettuce reconnects a lost one itself. */
    private Mono<StatefulRedisConnection<String, String>> connect() {
        StatefulRedisConnection<String, String> current = connection;
        if (current != null) {
            return Mono.just(current);
        }
        return Mono.fromCompletionStage(() -> client.connectAsync(StringCodec.UTF8, uri))
                .doOnNext(c -> {
                    synchronized (this) {
                        if (connection == null) {
                            connection = c;
                        } else {
                            c.closeAsync();
                        }
                    }
                })
                .map(c -> connection);
    }

    @Override
    public void close() {
        if (connection != null) {
            connection.close();
        }
        client.shutdown();
    }
}
