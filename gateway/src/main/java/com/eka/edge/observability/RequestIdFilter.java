package com.eka.edge.observability;

import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

/**
 * Gives every request an id before anything else runs, so even a rejected request is traceable.
 * A well-formed id from the caller is kept; anything else is replaced. The id goes to the core
 * and back to the client.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestIdFilter implements WebFilter {

    public static final String HEADER = "X-Request-Id";
    public static final String ATTRIBUTE = "eka.request-id";
    private static final Pattern VALID = Pattern.compile("[A-Za-z0-9._-]{8,64}");

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        String inbound = exchange.getRequest().getHeaders().getFirst(HEADER);
        String id = inbound != null && VALID.matcher(inbound).matches()
                ? inbound
                : UUID.randomUUID().toString().replace("-", "");
        exchange.getAttributes().put(ATTRIBUTE, id);
        exchange.getResponse().getHeaders().set(HEADER, id);
        ServerWebExchange mutated = exchange.mutate()
                .request(request -> request.headers(headers -> headers.set(HEADER, id)))
                .build();
        return chain.filter(mutated);
    }
}
