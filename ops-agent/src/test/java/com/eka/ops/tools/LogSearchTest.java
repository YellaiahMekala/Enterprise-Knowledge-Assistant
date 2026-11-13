package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class LogSearchTest {

    // Two streams, out of order, as Loki may return them. Times are 2026-11-11T10:00:0xZ.
    private static final String TWO_STREAMS = """
            {"status":"success","data":{"resultType":"streams","result":[
              {"stream":{"service":"api"},"values":[
                ["1794391201000000000","ERROR chat failed request_id=abc"],
                ["1794391203000000000","ERROR db timeout X-API-Key: sk-live-123 password=hunter2"]]},
              {"stream":{"service":"api","stream":"stderr"},"values":[
                ["1794391202000000000","ERROR Authorization: Bearer eyJabc.def"]]}]}}
            """;

    private HttpServer server;
    private String base;
    private final List<String> requests = new ArrayList<>();
    private int status = 200;
    private String body = TWO_STREAMS;

    @BeforeEach
    void startStub() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            requests.add(URLDecoder.decode(exchange.getRequestURI().getRawQuery(), StandardCharsets.UTF_8));
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.start();
        base = "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @AfterEach
    void stopStub() {
        server.stop(0);
    }

    private LogSearch search() {
        return new LogSearch(new ReadOnlyHttp(Duration.ofSeconds(2)), base);
    }

    @Test
    void theQueryIsBuiltHereFromTheServiceAndTheText() {
        search().search("api", "db timeout", 15);

        assertThat(requests).hasSize(1);
        assertThat(requests.get(0))
                .startsWith("query={service=\"api\"} |= \"db timeout\"")
                .contains("&since=15m")
                .contains("&limit=20")
                .contains("&direction=backward");
    }

    @Test
    void aLevelWordSearchesForWarningsAndErrorsAtAnyLevelName() {
        // Live run 2026-11-13: the core logs a database outage at WARNING, so a literal ERROR found nothing.
        for (String word : List.of("ERROR", "error", "WARN", "WARNING", " Errors ")) {
            requests.clear();
            search().search("api", word, 15);
            assertThat(requests.get(0))
                    .as(word)
                    .startsWith("query={service=\"api\"} |~ \"ERROR|WARN|CRITICAL|FATAL\"");
        }
    }

    @Test
    void anEmptyTextSearchesTheWholeServiceStream() {
        search().search("worker", "", 5);

        assertThat(requests.get(0)).startsWith("query={service=\"worker\"}&");
    }

    @Test
    void linesFromAllStreamsComeBackNewestFirstWithTimes() {
        String result = search().search("api", "ERROR", 15);

        assertThat(result).startsWith("3 newest line(s)");
        List<String> lines = result.lines().skip(1).toList();
        assertThat(lines).hasSize(3);
        assertThat(lines.get(0)).startsWith("2026-11-11T10:00:03Z ERROR db timeout");
        assertThat(lines.get(1)).startsWith("2026-11-11T10:00:02Z ");
        assertThat(lines.get(2)).startsWith("2026-11-11T10:00:01Z ERROR chat failed request_id=abc");
    }

    @Test
    void credentialsInLogLinesAreMasked() {
        String result = search().search("api", "ERROR", 15);

        assertThat(result)
                .doesNotContain("sk-live-123")
                .doesNotContain("hunter2")
                .doesNotContain("eyJabc")
                .contains("X-API-Key: ***")
                .contains("password=***")
                .contains("Authorization: Bearer ***");
    }

    @Test
    void argumentsOutsideTheRulesAreRefusedWithoutACall() {
        assertThat(search().search("postgres-prod", "x", 5)).startsWith("rejected: service must be one of");
        assertThat(search().search("api", "x\" |~ \".*", 5)).startsWith("rejected: the text may hold only");
        assertThat(search().search("api", "x`", 5)).startsWith("rejected:");
        assertThat(search().search("api", "a".repeat(101), 5)).startsWith("rejected: the text is longer");
        assertThat(search().search("api", "x", 0)).startsWith("rejected: minutes");
        assertThat(search().search("api", "x", 61)).startsWith("rejected: minutes");
        assertThat(requests).isEmpty();
    }

    @Test
    void noMatchesIsSaidPlainly() {
        body = "{\"status\":\"success\",\"data\":{\"resultType\":\"streams\",\"result\":[]}}";

        assertThat(search().search("edge", "panic", 10))
                .isEqualTo("no log lines for {service=\"edge\"} |= \"panic\" in the last 10 minutes");
    }

    @Test
    void aLokiErrorAndAnUnreadableAnswerComeBackAsText() {
        status = 400;
        body = "parse error at line 1";
        assertThat(search().search("api", "x", 5)).isEqualTo("HTTP 400 parse error at line 1");

        status = 200;
        body = "not json";
        assertThat(search().search("api", "x", 5)).contains("could not be read");
    }

    @Test
    void anUnreachableLogStoreIsReportedAsText() {
        server.stop(0);

        assertThat(search().search("api", "x", 5)).startsWith("unreachable");
    }

    @Test
    void longLinesAreCut() {
        body = "{\"data\":{\"result\":[{\"values\":[[\"1794391201000000000\",\"" + "y".repeat(500) + "\"]]}]}}";

        String line = search().search("api", "", 5).lines().skip(1).findFirst().orElseThrow();

        assertThat(line).hasSize("2026-11-11T10:00:01Z ".length() + LogSearch.MAX_LINE_CHARS + 3).endsWith("...");
    }
}
