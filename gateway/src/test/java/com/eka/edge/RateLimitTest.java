package com.eka.edge;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.edge.support.EdgeFixture;
import com.eka.edge.support.EdgeTestBase;
import com.eka.edge.support.Http;
import com.eka.edge.support.TestIdp;
import java.net.http.HttpResponse;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

class RateLimitTest extends EdgeTestBase {

    private static HttpResponse<String> call(String subject) {
        String token = EdgeFixture.IDP.sign(TestIdp.validClaims(subject).build());
        return Http.get(EdgeFixture.edge("/api/v1/documents"), "Authorization", Http.bearer(token));
    }

    @Test
    void aUserWhoBurstsPastTheLimitIsToldToWait() {
        List<HttpResponse<String>> responses = new ArrayList<>();
        for (int i = 0; i < 60; i++) {
            responses.add(call("noisy-user"));
        }

        var limited = responses.stream().filter(r -> r.statusCode() == 429).toList();
        assertThat(limited).isNotEmpty();
        assertThat(limited.get(0).headers().firstValue("retry-after")).isPresent();
        assertThat(limited.get(0).headers().firstValue("content-type"))
                .hasValueSatisfying(type -> assertThat(type).startsWith("application/problem+json"));
        assertThat(limited.get(0).body()).contains("urn:eka:problem:rate-limited");
    }

    @Test
    void oneUsersBurstDoesNotSlowAnother() {
        for (int i = 0; i < 60; i++) {
            call("hog");
        }
        assertThat(call("bystander").statusCode()).isEqualTo(200);
    }
}
