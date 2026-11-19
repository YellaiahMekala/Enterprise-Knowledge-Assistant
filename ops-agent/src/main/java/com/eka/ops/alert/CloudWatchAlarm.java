// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.alert;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Turns a CloudWatch alarm notification into the same {@link Alert} Alertmanager sends, so the
 * triage is identical on AWS. The alarm name is the alert name (they match the rules in
 * monitoring/alerts.yml, so the runbook lookup works); a description starting with
 * {@code [page]} or {@code [ticket]} gives the severity.
 *
 * <p>Accepts the SQS body with or without SNS's envelope (raw message delivery on or off).
 */
public final class CloudWatchAlarm {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final Pattern SEVERITY = Pattern.compile("^\\[(\\w+)]\\s*(.*)$", Pattern.DOTALL);
    // CloudWatch writes 2026-11-13T10:00:00.000+0000: an offset without a colon.
    private static final DateTimeFormatter TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSZ");

    private CloudWatchAlarm() {}

    /** Empty when the body is not an alarm notification. A state change to OK comes back resolved. */
    public static Optional<Alert> parse(String body) {
        JsonNode alarm;
        try {
            JsonNode node = JSON.readTree(body);
            if (node.has("Message") && node.path("Type").asString("").equals("Notification")) {
                node = JSON.readTree(node.get("Message").asString());
            }
            alarm = node;
        } catch (RuntimeException e) {
            return Optional.empty();
        }
        String name = alarm.path("AlarmName").asString("");
        String state = alarm.path("NewStateValue").asString("");
        if (name.isBlank() || state.isBlank()) {
            return Optional.empty();
        }
        String description = alarm.path("AlarmDescription").asString("");
        String severity = "unknown";
        Matcher m = SEVERITY.matcher(description);
        if (m.matches()) {
            severity = m.group(1);
            description = m.group(2);
        }
        Map<String, String> labels = new LinkedHashMap<>();
        labels.put("alertname", name);
        labels.put("severity", severity);
        labels.put("source", "cloudwatch");
        Map<String, String> annotations = new LinkedHashMap<>();
        annotations.put("summary", description);
        annotations.put("reason", alarm.path("NewStateReason").asString(""));
        return Optional.of(new Alert(
                "ALARM".equals(state) ? "firing" : "resolved",
                labels,
                annotations,
                time(alarm.path("StateChangeTime").asString(""))));
    }

    private static Instant time(String text) {
        try {
            return OffsetDateTime.parse(text, TIME).toInstant();
        } catch (RuntimeException e) {
            return Instant.now();
        }
    }
}
