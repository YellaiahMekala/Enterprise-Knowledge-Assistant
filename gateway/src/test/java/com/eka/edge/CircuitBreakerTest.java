package com.eka.edge;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.edge.support.EdgeFixture;
import com.eka.edge.support.EdgeTestBase;
import com.eka.edge.support.Http;
import com.eka.edge.support.TestIdp;
import java.net.http.HttpResponse;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;

/**
 * After enough timeouts the edge stops calling the core and answers 503 at once. It leaves the
 * breaker open, so it runs last (see junit-platform.properties) in the shared application context.
 */
@Order(Integer.MAX_VALUE)
class CircuitBreakerTest extends EdgeTestBase {

    private static HttpResponse<String> call(String path, String subject) {
        String token = EdgeFixture.IDP.sign(TestIdp.validClaims(subject).build());
        return Http.get(EdgeFixture.edge(path), "Authorization", Http.bearer(token));
    }

    @Test
    void repeatedTimeoutsOpenTheCircuitAndLaterCallsFailFast() throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(24);
        try {
            List<Future<HttpResponse<String>>> calls = new ArrayList<>();
            for (int i = 0; i < 24; i++) {
                String user = "cb-user-" + i;
                calls.add(pool.submit(() -> call("/api/v1/drill/hang", user)));
            }
            for (Future<HttpResponse<String>> f : calls) {
                f.get();
            }
        } finally {
            pool.shutdownNow();
        }

        long started = System.currentTimeMillis();
        HttpResponse<String> response = call("/api/v1/drill/hang", "cb-user-after");

        assertThat(response.statusCode()).isEqualTo(503);
        assertThat(response.body()).contains("urn:eka:problem:circuit-open").doesNotContain("Exception");
        assertThat(System.currentTimeMillis() - started).as("no call reached the core").isLessThan(1_000);

        // The alert rule EkaEdgeCircuitOpen reads this series.
        String metrics = Http.get(EdgeFixture.management("/actuator/prometheus")).body();
        assertThat(metrics).containsPattern("resilience4j_circuitbreaker_state\\{[^}]*name=\"core\"[^}]*state=\"open\"[^}]*} 1\\.0");
    }
}
