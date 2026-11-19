// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.token;

import com.eka.edge.error.ProblemWriter;
import com.eka.edge.observability.RequestIdFilter;
import com.eka.edge.ratelimit.RateLimiter;
import com.eka.edge.security.Identity;
import com.eka.edge.security.IdentityMapper;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.context.ReactiveSecurityContextHolder;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * The credential swap. Whatever identity the client proved, the core receives only a fresh
 * internal token. The client's own token, API keys, cookies and any {@code X-Auth-*} header are
 * removed first, so nothing the client sends can pose as the edge.
 */
@Component
public class InternalTokenFilter implements GlobalFilter, Ordered {

    private static final Logger audit = LoggerFactory.getLogger("eka.audit");

    private static final String API_KEY_HEADER = "X-API-Key";
    private static final String AUTH_HEADER_PREFIX = "X-Auth-";

    private final InternalTokenService tokens;
    private final IdentityMapper identities;
    private final RateLimiter limiter;
    private final ProblemWriter problems;

    public InternalTokenFilter(
            InternalTokenService tokens,
            IdentityMapper identities,
            RateLimiter limiter,
            ProblemWriter problems) {
        this.tokens = tokens;
        this.identities = identities;
        this.limiter = limiter;
        this.problems = problems;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        return ReactiveSecurityContextHolder.getContext()
                .map(SecurityContext::getAuthentication)
                .filter(JwtAuthenticationToken.class::isInstance)
                .cast(JwtAuthenticationToken.class)
                .switchIfEmpty(Mono.error(new ResponseStatusException(HttpStatus.UNAUTHORIZED)))
                .map(authentication -> identities.from(authentication.getToken()))
                .flatMap(identity -> limiter.tryAcquire(identity.userId()).flatMap(decision -> {
                    if (!decision.allowed()) {
                        long seconds = Math.max(1, decision.retryAfter().toSeconds());
                        exchange.getResponse().getHeaders().set(HttpHeaders.RETRY_AFTER, Long.toString(seconds));
                        return problems.write(
                                exchange, HttpStatus.TOO_MANY_REQUESTS, "rate-limited",
                                "Too many requests. Try again shortly.");
                    }
                    Object attribute = exchange.getAttribute(RequestIdFilter.ATTRIBUTE);
                    String requestId = attribute == null ? "-" : attribute.toString();
                    audit.info("user={} role={} method={} path={} request_id={}",
                            identity.userId(), identity.role(),
                            exchange.getRequest().getMethod(), exchange.getRequest().getPath(), requestId);
                    String internal = tokens.mint(identity.userId(), identity.role(), requestId);
                    var request = exchange.getRequest().mutate()
                            .headers(headers -> {
                                headers.remove(HttpHeaders.AUTHORIZATION);
                                headers.remove(HttpHeaders.COOKIE);
                                headers.remove(API_KEY_HEADER);
                                List.copyOf(headers.headerNames()).stream()
                                        .filter(name -> name.regionMatches(
                                                true, 0, AUTH_HEADER_PREFIX, 0, AUTH_HEADER_PREFIX.length()))
                                        .forEach(headers::remove);
                                headers.set(HttpHeaders.AUTHORIZATION, "Bearer " + internal);
                            })
                            .build();
                    return chain.filter(exchange.mutate().request(request).build());
                }));
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE + 10;
    }
}
