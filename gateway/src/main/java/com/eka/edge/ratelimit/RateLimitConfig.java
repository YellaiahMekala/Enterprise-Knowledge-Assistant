// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.ratelimit;

import com.eka.edge.config.EdgeProperties;
import java.time.Clock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Redis when {@code eka.edge.rate-limit.redis-url} is set (several edge tasks), memory otherwise. */
@Configuration
class RateLimitConfig {

    private static final Logger log = LoggerFactory.getLogger(RateLimitConfig.class);

    @Bean
    RateLimiter rateLimiter(EdgeProperties properties, Clock clock) {
        EdgeProperties.RateLimit limit = properties.rateLimit();
        if (limit.redisUrl() == null) {
            log.info("rate limit: in memory, per edge instance");
            return new LocalRateLimiter(limit, clock);
        }
        log.info("rate limit: shared in Redis");
        return new RedisRateLimiter(limit.redisUrl(), limit, limit.redisTimeout());
    }
}
