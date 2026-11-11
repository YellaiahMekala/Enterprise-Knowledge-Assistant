package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * Against a real Loki fed by Alloy (docker compose --profile monitoring up -d api loki alloy), after
 * a failed sign-in such as: curl -H "X-API-Key: wrong" http://127.0.0.1:8000/api/v1/me.
 * Skipped unless EKA_LIVE_LOKI_URL is set, for example http://127.0.0.1:3100.
 */
@EnabledIfEnvironmentVariable(named = "EKA_LIVE_LOKI_URL", matches = "http.+")
class LogSearchLiveTest {

    private final LogSearch search =
            new LogSearch(new ReadOnlyHttp(Duration.ofSeconds(5)), System.getenv("EKA_LIVE_LOKI_URL"));

    @Test
    void findsTheCoresFailedSignInLines() {
        String result = search.search("api", "authentication failed", 60);

        assertThat(result).contains("newest line(s) for {service=\"api\"} |= \"authentication failed\"");
        assertThat(result.lines().skip(1)).allSatisfy(line -> assertThat(line).contains("authentication failed"));
    }

    @Test
    void aServiceWithNoMatchingLinesSaysSo() {
        assertThat(search.search("worker", "no-such-text-xyz", 5)).startsWith("no log lines for");
    }
}
