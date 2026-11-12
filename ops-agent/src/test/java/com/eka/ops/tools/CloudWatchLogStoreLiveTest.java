package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import software.amazon.awssdk.services.cloudwatchlogs.CloudWatchLogsClient;
import software.amazon.awssdk.services.cloudwatchlogs.model.CreateLogGroupRequest;
import software.amazon.awssdk.services.cloudwatchlogs.model.CreateLogStreamRequest;
import software.amazon.awssdk.services.cloudwatchlogs.model.DeleteLogGroupRequest;
import software.amazon.awssdk.services.cloudwatchlogs.model.InputLogEvent;
import software.amazon.awssdk.services.cloudwatchlogs.model.PutLogEventsRequest;
import software.amazon.awssdk.services.cloudwatchlogs.model.ResourceAlreadyExistsException;

/**
 * Against a real CloudWatch Logs API: LocalStack locally (docker run -p 4566:4566
 * localstack/localstack) with EKA_LIVE_CLOUDWATCH_ENDPOINT=http://127.0.0.1:4566 and any
 * AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_REGION set; or real AWS with the endpoint
 * set to "aws" and the default credential chain. Skipped otherwise.
 */
@EnabledIfEnvironmentVariable(named = "EKA_LIVE_CLOUDWATCH_ENDPOINT", matches = ".+")
class CloudWatchLogStoreLiveTest {

    private static final String GROUP = "/eka-live-test-" + System.nanoTime(); // a fresh group per run
    private static final String STREAM = "eka/core/" + System.nanoTime();

    private static CloudWatchLogStore store;
    private static CloudWatchLogsClient client;

    @BeforeAll
    static void writeThreeLines() {
        String endpoint = System.getenv("EKA_LIVE_CLOUDWATCH_ENDPOINT");
        store = CloudWatchLogStore.connect(GROUP, "aws".equals(endpoint) ? null : endpoint, Duration.ofSeconds(10));
        client = CloudWatchLogStore.connect(GROUP, "aws".equals(endpoint) ? null : endpoint, Duration.ofSeconds(10))
                .client();
        try {
            client.createLogGroup(CreateLogGroupRequest.builder().logGroupName(GROUP).build());
        } catch (ResourceAlreadyExistsException ignored) {
            // not expected with a fresh name
        }
        client.createLogStream(CreateLogStreamRequest.builder().logGroupName(GROUP).logStreamName(STREAM).build());
        long now = System.currentTimeMillis();
        client.putLogEvents(PutLogEventsRequest.builder()
                .logGroupName(GROUP)
                .logStreamName(STREAM)
                .logEvents(List.of(
                        InputLogEvent.builder().timestamp(now - 3000).message("INFO GET /health/ready 200").build(),
                        InputLogEvent.builder().timestamp(now - 2000)
                                .message("WARNING authentication failed: unknown credential X-API-Key: sk-live-1").build(),
                        InputLogEvent.builder().timestamp(now - 1000).message("ERROR chat failed request_id=abc").build()))
                .build());
    }

    @AfterAll
    static void removeTheGroup() {
        client.deleteLogGroup(DeleteLogGroupRequest.builder().logGroupName(GROUP).build());
    }

    @Test
    void findsTheLinesItWroteNewestFirstAndMasked() throws InterruptedException {
        String result = "";
        for (int attempt = 0; attempt < 10 && !result.startsWith("2 newest"); attempt++) {
            Thread.sleep(500); // the API is eventually consistent
            result = new LogSearch(store).search("api", "failed", 5);
        }

        assertThat(result).startsWith("2 newest line(s) for " + GROUP + " eka/core/* pattern \"failed\":\n");
        List<String> lines = result.lines().skip(1).toList();
        assertThat(lines.get(0)).contains("ERROR chat failed");
        assertThat(lines.get(1)).contains("authentication failed").contains("X-API-Key: ***").doesNotContain("sk-live-1");
    }

    @Test
    void aTextThatMatchesNothingSaysSo() {
        assertThat(new LogSearch(store).search("api", "no-such-text-xyz", 5)).startsWith("no log lines for " + GROUP);
    }

    @Test
    void aMissingGroupIsAnErrorLineNotACrash() {
        CloudWatchLogStore missing = new CloudWatchLogStore(client, "/eka-no-such-group");

        assertThat(new LogSearch(missing).search("api", "x", 5)).startsWith("CloudWatch Logs: ResourceNotFoundException");
    }
}
