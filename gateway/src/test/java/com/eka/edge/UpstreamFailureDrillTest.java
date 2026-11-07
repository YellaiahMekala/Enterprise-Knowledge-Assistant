package com.eka.edge;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.edge.support.EdgeFixture;
import com.eka.edge.support.EdgeTestBase;
import com.eka.edge.support.Http;
import com.eka.edge.support.TestIdp;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;

/** What a client sees when the core misbehaves: a clean problem document, never internals. */
class UpstreamFailureDrillTest extends EdgeTestBase {

    private static HttpResponse<String> call(String path, String subject) {
        String token = EdgeFixture.IDP.sign(TestIdp.validClaims(subject).build());
        return Http.get(EdgeFixture.edge(path), "Authorization", Http.bearer(token));
    }

    private static void assertProblem(HttpResponse<String> response, int status, String slug) {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(response.headers().firstValue("content-type"))
                .hasValueSatisfying(type -> assertThat(type).startsWith("application/problem+json"));
        assertThat(response.body())
                .contains("urn:eka:problem:" + slug)
                .contains("request_id")
                .doesNotContain("Exception")
                .doesNotContain("127.0.0.1")
                .doesNotContain("reactor");
    }

    @Test
    void aCoreThatDoesNotAnswerInTimeBecomesA504() {
        long started = System.currentTimeMillis();
        HttpResponse<String> response = call("/api/v1/drill/hang", "drill-slow");
        assertProblem(response, 504, "gateway-timeout");
        assertThat(System.currentTimeMillis() - started).as("gave up near the timeout").isLessThan(5_000);
    }
}
