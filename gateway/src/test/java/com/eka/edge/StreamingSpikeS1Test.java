package com.eka.edge;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.edge.support.EdgeFixture;
import com.eka.edge.support.EdgeTestBase;
import com.eka.edge.support.Http;
import com.eka.edge.support.StubCore;
import com.eka.edge.support.TestIdp;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * Spike S-1 (ADR-023): can the edge pass server-sent events through without buffering, and does
 * a client that leaves stop the upstream? The stub core emits one event every half second for
 * three seconds, so buffering or a missing cancel is visible in the timings.
 */
class StreamingSpikeS1Test extends EdgeTestBase {

    private static final long TOTAL_MS = StubCore.STREAM_EVENTS * StubCore.STREAM_INTERVAL_MS;

    private static HttpResponse<InputStream> open() {
        String token = EdgeFixture.IDP.sign(TestIdp.validClaims("streamer").build());
        return Http.stream(
                EdgeFixture.edge("/api/v1/stream"),
                "Authorization", Http.bearer(token),
                "Accept", "text/event-stream",
                "X-Request-Id", "stream-request-0001");
    }

    /** Reads until one complete event (a blank line) and returns its time of arrival. */
    private static long readEvent(BufferedReader reader) throws IOException {
        String line;
        boolean sawData = false;
        while ((line = reader.readLine()) != null) {
            if (line.startsWith("data:")) {
                sawData = true;
            }
            if (line.isEmpty() && sawData) {
                return System.currentTimeMillis();
            }
        }
        throw new IOException("the stream ended before an event completed");
    }

    /** The first request pays for key-set retrieval and class loading; take that out of the timings. */
    private static void warmUp() {
        String token = EdgeFixture.IDP.sign(TestIdp.validClaims("warm-up").build());
        Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token));
    }

    @Test
    void eventsAreDeliveredAsTheyAreProducedNotAtTheEnd() throws Exception {
        warmUp();
        EdgeFixture.CORE.awaitIdle();
        EdgeFixture.CORE.resetStream();
        long requested = System.currentTimeMillis();

        HttpResponse<InputStream> response = open();
        assertThat(response.statusCode()).isEqualTo(200);
        assertThat(response.headers().firstValue("content-type")).hasValueSatisfying(
                type -> assertThat(type).startsWith("text/event-stream"));

        List<Long> arrivals = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(response.body(), StandardCharsets.UTF_8))) {
            for (int i = 0; i < StubCore.STREAM_EVENTS; i++) {
                arrivals.add(readEvent(reader));
            }
        }

        long firstAfter = arrivals.get(0) - requested;
        long spread = arrivals.get(arrivals.size() - 1) - arrivals.get(0);
        System.out.printf(
                "S-1: first event after %d ms; %d events spread over %d ms (upstream takes %d ms)%n",
                firstAfter, arrivals.size(), spread, TOTAL_MS);

        assertThat(firstAfter)
                .as("the first event must not wait for the upstream to finish")
                .isLessThan(StubCore.STREAM_INTERVAL_MS);
        assertThat(spread)
                .as("events arrive spread out, not in one burst")
                .isGreaterThan((StubCore.STREAM_EVENTS - 1) * StubCore.STREAM_INTERVAL_MS * 7 / 10);
        assertThat(EdgeFixture.CORE.lastStreamRequestId()).isEqualTo("stream-request-0001");
        EdgeFixture.CORE.awaitIdle();
    }

    @Test
    void aClientThatLeavesStopsTheUpstream() throws Exception {
        warmUp();
        EdgeFixture.CORE.awaitIdle();
        EdgeFixture.CORE.resetStream();

        HttpResponse<InputStream> response = open();
        BufferedReader reader =
                new BufferedReader(new InputStreamReader(response.body(), StandardCharsets.UTF_8));
        readEvent(reader);
        long left = System.currentTimeMillis();
        reader.close(); // the browser tab closes

        long deadline = left + 5_000;
        while (EdgeFixture.CORE.clientGoneAt() == 0 && System.currentTimeMillis() < deadline) {
            Thread.sleep(50);
        }
        long noticedAfter = EdgeFixture.CORE.clientGoneAt() - left;
        System.out.printf("S-1: upstream noticed the departure %d ms after the client left%n", noticedAfter);

        assertThat(EdgeFixture.CORE.clientGoneAt()).as("the upstream noticed the client left").isPositive();
        assertThat(noticedAfter).as("within the grace period").isLessThan(3_000);
        assertThat(EdgeFixture.CORE.streamCompletedAt())
                .as("the upstream did not run to completion for nobody")
                .isZero();
    }
}
