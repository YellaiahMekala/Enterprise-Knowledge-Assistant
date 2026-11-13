package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;
import org.junit.jupiter.api.Test;
import software.amazon.awssdk.services.cloudwatchlogs.CloudWatchLogsClient;
import software.amazon.awssdk.services.cloudwatchlogs.model.FilterLogEventsRequest;
import software.amazon.awssdk.services.cloudwatchlogs.model.FilterLogEventsResponse;
import software.amazon.awssdk.services.cloudwatchlogs.model.FilteredLogEvent;
import software.amazon.awssdk.services.cloudwatchlogs.model.ResourceNotFoundException;

/** Against a stand-in client: what the store asks CloudWatch, and how it reads the answer. */
class CloudWatchLogStoreTest {

    private static final long T0 = 1_794_391_200_000L; // 2026-11-11T10:00:00Z

    private final List<FilterLogEventsRequest> requests = new ArrayList<>();

    /** The SDK client is an interface whose methods throw unless overridden; only one is needed. */
    private CloudWatchLogsClient client(Function<FilterLogEventsRequest, FilterLogEventsResponse> answer) {
        return new CloudWatchLogsClient() {
            @Override
            public FilterLogEventsResponse filterLogEvents(FilterLogEventsRequest request) {
                requests.add(request);
                return answer.apply(request);
            }

            @Override
            public String serviceName() {
                return "cloudwatchlogs";
            }

            @Override
            public void close() {}
        };
    }

    private static FilteredLogEvent event(long offsetSeconds, String message) {
        return FilteredLogEvent.builder().timestamp(T0 + offsetSeconds * 1000).message(message).build();
    }

    private static FilterLogEventsResponse page(String next, FilteredLogEvent... events) {
        return FilterLogEventsResponse.builder().events(events).nextToken(next).build();
    }

    @Test
    void theRequestNamesTheGroupTheContainerStreamAndAQuotedTerm() {
        CloudWatchLogStore store = new CloudWatchLogStore(client(r -> page(null)), "/eka");
        long before = System.currentTimeMillis();

        List<LogStore.Line> lines = store.newest("core-behind-edge", "ERROR chat", 15, 20);

        assertThat(lines).isEmpty();
        FilterLogEventsRequest request = requests.get(0);
        assertThat(request.logGroupName()).isEqualTo("/eka");
        assertThat(request.logStreamNamePrefix()).isEqualTo("eka/core/");
        assertThat(request.filterPattern()).isEqualTo("\"ERROR chat\"");
        assertThat(request.limit()).isEqualTo(CloudWatchLogStore.PAGE_SIZE);
        assertThat(request.startTime()).isBetween(before - 15 * 60_000L - 1000, before - 15 * 60_000L + 1000);
    }

    @Test
    void anEmptyTextHasNoFilterPattern() {
        CloudWatchLogStore store = new CloudWatchLogStore(client(r -> page(null)), "/eka");

        store.newest("worker", "", 5, 20);

        assertThat(requests.get(0).filterPattern()).isNull();
        assertThat(requests.get(0).logStreamNamePrefix()).isEqualTo("eka/worker/");
    }

    @Test
    void aLevelWordBecomesAnOrPatternAndKeepsWarningLines() {
        CloudWatchLogStore store = new CloudWatchLogStore(
                client(r -> page(null,
                        event(1, "INFO GET /health/ready 200"),
                        event(2, "WARNING readiness check failed: OperationalError"),
                        event(3, "WARN reset by peer"),
                        event(4, "ERROR Unhandled exception"))),
                "/eka");

        List<LogStore.Line> lines = store.newest("api", "ERROR", 10, 20);

        assertThat(requests.get(0).filterPattern()).isEqualTo("?\"ERROR\" ?\"WARN\" ?\"CRITICAL\" ?\"FATAL\"");
        // The stub ignores the pattern, so this also checks the local filter: the INFO line is dropped.
        assertThat(lines).extracting(LogStore.Line::text).containsExactly(
                "ERROR Unhandled exception", "WARN reset by peer", "WARNING readiness check failed: OperationalError");
    }

    @Test
    void theNewestLinesAreKeptAcrossPagesAndReturnedNewestFirst() {
        CloudWatchLogStore store = new CloudWatchLogStore(
                client(r -> r.nextToken() == null
                        ? page("p2", event(1, "x one"), event(2, "x two"), event(3, "x three"))
                        : page(null, event(4, "x four"), event(5, "x five"))),
                "/eka");

        List<LogStore.Line> lines = store.newest("api", "x", 10, 3);

        assertThat(requests).hasSize(2);
        assertThat(requests.get(1).nextToken()).isEqualTo("p2");
        assertThat(lines).extracting(LogStore.Line::text).containsExactly("x five", "x four", "x three");
        assertThat(lines.get(0).time()).isEqualTo("2026-11-11T10:00:05Z");
    }

    @Test
    void aWindowWithTooManyPagesStopsAfterTheLimit() {
        CloudWatchLogStore store = new CloudWatchLogStore(client(r -> page("more", event(1, "x line"))), "/eka");

        store.newest("api", "x", 60, 20);

        assertThat(requests).hasSize(CloudWatchLogStore.MAX_PAGES);
    }

    @Test
    void aServiceWithoutAContainerOnAwsIsSaidPlainly() {
        CloudWatchLogStore store = new CloudWatchLogStore(client(r -> page(null)), "/eka");

        assertThat(new LogSearch(store).search("db", "x", 5)).isEqualTo("db does not run as a container on AWS, so it has no log stream");
        assertThat(new LogSearch(store).search("prometheus", "x", 5)).contains("has no log stream");
        assertThat(requests).isEmpty();
    }

    @Test
    void anAwsErrorComesBackAsOneShortLineOfText() {
        CloudWatchLogStore store = new CloudWatchLogStore(
                client(r -> {
                    throw ResourceNotFoundException.builder()
                            .message("The specified log group does not exist.\n(Service: CloudWatchLogs)")
                            .build();
                }),
                "/missing");

        assertThat(new LogSearch(store).search("api", "x", 5))
                .isEqualTo("CloudWatch Logs: ResourceNotFoundException: The specified log group does not exist.");
    }

    @Test
    void theSearchFormatsAndMasksCloudWatchLinesLikeLokiOnes() {
        CloudWatchLogStore store = new CloudWatchLogStore(
                client(r -> page(null, event(1, "ERROR db timeout password=hunter2"))), "/eka");

        String result = new LogSearch(store).search("api", "ERROR", 5);

        assertThat(result)
                .startsWith("1 newest line(s) for /eka eka/core/* pattern ?\"ERROR\" ?\"WARN\" ?\"CRITICAL\" ?\"FATAL\":\n")
                .contains("2026-11-11T10:00:01Z ERROR db timeout password=***")
                .doesNotContain("hunter2");
    }

    @Test
    void theStoresQueryDescriptionNamesTheGroupAndStream() {
        CloudWatchLogStore store = new CloudWatchLogStore(client(r -> page(null)), "/eka");

        assertThat(store.describe("edge", "")).isEqualTo("/eka eka/edge/*");
        assertThat(store.describe("edge", "panic")).isEqualTo("/eka eka/edge/* pattern \"panic\"");
        assertThatThrownBy(() -> store.newest("alertmanager", "", 5, 20))
                .isInstanceOf(LogStore.LogStoreException.class);
    }
}
