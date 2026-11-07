package com.eka.edge.error;

import io.netty.handler.timeout.TimeoutException;
import java.net.ConnectException;
import java.net.UnknownHostException;
import java.nio.channels.ClosedChannelException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebExceptionHandler;
import reactor.core.publisher.Mono;

/**
 * Turns a failure talking to the core into the same problem document the core uses. The cause
 * is logged with the request id; the client gets fixed text only.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 100)
public class UpstreamErrorHandler implements WebExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(UpstreamErrorHandler.class);

    public record Mapped(HttpStatus status, String slug, String detail) {}

    private final ProblemWriter problems;

    public UpstreamErrorHandler(ProblemWriter problems) {
        this.problems = problems;
    }

    @Override
    public Mono<Void> handle(ServerWebExchange exchange, Throwable error) {
        Mapped mapped = map(error);
        if (mapped == null) {
            return Mono.error(error);
        }
        log.warn("upstream failure on {}: {}", exchange.getRequest().getPath(), summary(error));
        return problems.write(exchange, mapped.status(), mapped.slug(), mapped.detail());
    }

    /** Null when the failure is not about reaching the core. */
    static Mapped map(Throwable error) {
        for (Throwable t = error; t != null; t = t.getCause()) {
            if (t instanceof TimeoutException || t instanceof java.util.concurrent.TimeoutException) {
                return new Mapped(HttpStatus.GATEWAY_TIMEOUT, "gateway-timeout", "The service took too long to answer.");
            }
            if (t instanceof ConnectException || t instanceof UnknownHostException) {
                return new Mapped(HttpStatus.SERVICE_UNAVAILABLE, "unavailable", "The service is unavailable.");
            }
            if (t instanceof ClosedChannelException || t.getClass().getSimpleName().equals("PrematureCloseException")) {
                return new Mapped(HttpStatus.BAD_GATEWAY, "bad-gateway", "The service closed the connection.");
            }
            if (t instanceof ResponseStatusException rse) {
                HttpStatus status = HttpStatus.resolve(rse.getStatusCode().value());
                if (status == HttpStatus.GATEWAY_TIMEOUT) {
                    return new Mapped(status, "gateway-timeout", "The service took too long to answer.");
                }
                if (status == HttpStatus.BAD_GATEWAY) {
                    return new Mapped(status, "bad-gateway", "The service closed the connection.");
                }
                if (status == HttpStatus.SERVICE_UNAVAILABLE) {
                    return new Mapped(status, "unavailable", "The service is unavailable.");
                }
            }
        }
        return null;
    }

    private static String summary(Throwable error) {
        Throwable root = error;
        while (root.getCause() != null) {
            root = root.getCause();
        }
        return root.getClass().getSimpleName();
    }
}
