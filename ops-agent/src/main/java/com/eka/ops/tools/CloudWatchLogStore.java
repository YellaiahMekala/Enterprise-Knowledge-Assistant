// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import java.net.URI;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import software.amazon.awssdk.core.exception.SdkException;
import software.amazon.awssdk.services.cloudwatchlogs.CloudWatchLogsClient;
import software.amazon.awssdk.services.cloudwatchlogs.model.FilterLogEventsRequest;
import software.amazon.awssdk.services.cloudwatchlogs.model.FilterLogEventsResponse;
import software.amazon.awssdk.services.cloudwatchlogs.model.FilteredLogEvent;

/**
 * CloudWatch Logs, where the Terraform in infra/aws sends every container's output: one log group
 * per deployment and one stream per container, named {@code eka/<container>/<task id>}. The
 * Compose service names the model knows are mapped to those container names; services that do
 * not run on AWS (the database is RDS, Prometheus is not deployed) have no stream and say so.
 */
public class CloudWatchLogStore implements LogStore {

    /** Compose service name to the ECS container name in infra/aws/ecs.tf. */
    static final Map<String, String> CONTAINERS = Map.of(
            "api", "core",
            "core-behind-edge", "core",
            "worker", "worker",
            "edge", "edge",
            "ops-agent", "ops-agent");
    static final String STREAM_PREFIX = "eka/";
    /** FilterLogEvents returns oldest first, so a busy window takes several pages to reach the end. */
    static final int MAX_PAGES = 5;
    static final int PAGE_SIZE = 10_000;

    private final CloudWatchLogsClient client;
    private final String logGroup;

    public CloudWatchLogStore(CloudWatchLogsClient client, String logGroup) {
        this.client = client;
        this.logGroup = logGroup;
    }

    /** Region and credentials come from the AWS default chain; the endpoint is for a local stand-in. */
    public static CloudWatchLogStore connect(String logGroup, String endpointUrl, Duration timeout) {
        var builder = CloudWatchLogsClient.builder()
                .overrideConfiguration(c -> c.apiCallTimeout(timeout).apiCallAttemptTimeout(timeout));
        if (endpointUrl != null && !endpointUrl.isBlank()) {
            builder.endpointOverride(URI.create(endpointUrl));
        }
        return new CloudWatchLogStore(builder.build(), logGroup);
    }

    CloudWatchLogsClient client() {
        return client;
    }

    static String streamPrefix(String service) {
        String container = CONTAINERS.get(service);
        return container == null ? null : STREAM_PREFIX + container + "/";
    }

    /** The checked text goes into a CloudWatch filter pattern as one quoted term; it has no quotes. */
    static String filterPattern(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        if (LogLevels.isLevelSearch(text)) {
            // "?" terms are ORed in a CloudWatch filter pattern.
            return String.join(" ", LogLevels.PROBLEM_TERMS.stream().map(t -> "?\"" + t + "\"").toList());
        }
        return "\"" + text.strip() + "\"";
    }

    @Override
    public String describe(String service, String text) {
        String pattern = filterPattern(text);
        return logGroup + " " + STREAM_PREFIX + CONTAINERS.getOrDefault(service, service) + "/*"
                + (pattern == null ? "" : " pattern " + pattern);
    }

    @Override
    public List<Line> newest(String service, String text, int minutes, int limit) {
        String prefix = streamPrefix(service);
        if (prefix == null) {
            throw new LogStoreException(service + " does not run as a container on AWS, so it has no log stream");
        }
        long since = Instant.now().minus(Duration.ofMinutes(minutes)).toEpochMilli();
        Deque<FilteredLogEvent> newest = new ArrayDeque<>(limit + 1);
        String token = null;
        String needle = text == null || text.isBlank() ? null : text.strip();
        try {
            for (int page = 0; page < MAX_PAGES; page++) {
                FilterLogEventsRequest.Builder request = FilterLogEventsRequest.builder()
                        .logGroupName(logGroup)
                        .logStreamNamePrefix(prefix)
                        .startTime(since)
                        .limit(PAGE_SIZE)
                        .nextToken(token);
                String pattern = filterPattern(text);
                if (pattern != null) {
                    request.filterPattern(pattern);
                }
                FilterLogEventsResponse response = client.filterLogEvents(request.build());
                for (FilteredLogEvent event : response.events()) {
                    // The server filters too; checking here keeps stand-ins that ignore patterns honest.
                    if (needle != null && !LogLevels.matches(event.message(), needle)) {
                        continue;
                    }
                    newest.addLast(event); // oldest first; keep only the tail
                    if (newest.size() > limit) {
                        newest.removeFirst();
                    }
                }
                token = response.nextToken();
                if (token == null) {
                    break;
                }
            }
        } catch (SdkException e) {
            throw new LogStoreException("CloudWatch Logs: " + e.getClass().getSimpleName() + ": " + firstLine(e));
        }
        List<Line> lines = new ArrayList<>(newest.size());
        for (FilteredLogEvent event : newest) {
            lines.add(new Line(event.timestamp() * 1_000_000L, event.message()));
        }
        lines.sort((a, b) -> Long.compare(b.nanos(), a.nanos()));
        return lines;
    }

    private static String firstLine(Exception e) {
        String message = e.getMessage() == null ? "" : e.getMessage();
        int end = message.indexOf('\n');
        message = end < 0 ? message : message.substring(0, end);
        return message.length() > 200 ? message.substring(0, 200) : message;
    }
}
