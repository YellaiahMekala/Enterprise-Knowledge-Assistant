// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.error;

import com.eka.edge.observability.RequestIdFilter;
import java.nio.charset.StandardCharsets;
import java.util.regex.Pattern;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * Writes RFC 9457 problem responses in the same shape as the core's, so a client sees one error
 * format whichever service answered. Detail is fixed text: no token content, no stack trace.
 */
@Component
public class ProblemWriter {

    public static final MediaType PROBLEM_JSON = MediaType.parseMediaType("application/problem+json");
    private static final Pattern SAFE = Pattern.compile("[A-Za-z0-9._~/-]{0,200}");

    public Mono<Void> unauthorized(ServerWebExchange exchange) {
        exchange.getResponse().getHeaders().set(HttpHeaders.WWW_AUTHENTICATE, "Bearer");
        return write(exchange, HttpStatus.UNAUTHORIZED, "unauthorized", "A valid access token is required.");
    }

    public Mono<Void> forbidden(ServerWebExchange exchange) {
        return write(exchange, HttpStatus.FORBIDDEN, "forbidden", "You are not allowed to do this.");
    }

    public Mono<Void> write(ServerWebExchange exchange, HttpStatus status, String slug, String detail) {
        var response = exchange.getResponse();
        if (response.isCommitted()) {
            return Mono.empty();
        }
        response.setStatusCode(status);
        response.getHeaders().setContentType(PROBLEM_JSON);
        String body = "{\"type\":\"urn:eka:problem:" + slug + "\","
                + "\"title\":\"" + status.getReasonPhrase() + "\","
                + "\"status\":" + status.value() + ","
                + "\"detail\":\"" + detail + "\","
                + "\"instance\":\"" + safe(exchange.getRequest().getPath().value()) + "\","
                + "\"request_id\":\"" + safe(requestId(exchange)) + "\"}";
        DataBuffer buffer = response.bufferFactory().wrap(body.getBytes(StandardCharsets.UTF_8));
        return response.writeWith(Mono.just(buffer));
    }

    private static String requestId(ServerWebExchange exchange) {
        Object attribute = exchange.getAttribute(RequestIdFilter.ATTRIBUTE);
        return attribute == null ? "-" : attribute.toString();
    }

    /** Only characters that cannot break out of a JSON string are echoed. */
    private static String safe(String value) {
        return SAFE.matcher(value).matches() ? value : "-";
    }
}
