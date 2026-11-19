// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.alert;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.delivery.ReportDelivery;
import com.eka.ops.mail.ReportMailer;
import com.eka.ops.triage.TriageService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.DeleteMessageRequest;
import software.amazon.awssdk.services.sqs.model.DeleteMessageResponse;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageRequest;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageResponse;

/** CloudWatch alarm notifications, as SNS puts them on the queue, become the agent's alerts. */
class SqsAlarmPollerTest {

    static final String ALARM = """
            {"AlarmName":"EkaHighErrorRate","AlarmDescription":"[page] More than 7.2% of requests fail with 5xx",\
            "NewStateValue":"ALARM","NewStateReason":"Threshold Crossed: 1 datapoint [0.31] was greater than 0.072",\
            "StateChangeTime":"2026-11-13T10:00:00.000+0000"}""";

    static String envelope(String alarm) {
        String quoted = alarm.replace("\\", "\\\\").replace("\"", "\\\"");
        return "{\"Type\":\"Notification\",\"TopicArn\":\"arn:aws:sns:eu-west-1:1:eka-alarms\",\"Message\":\"" + quoted + "\"}";
    }

    @Test
    void anAlarmInsideTheSnsEnvelopeBecomesAFiringAlert() {
        Alert alert = CloudWatchAlarm.parse(envelope(ALARM)).orElseThrow();

        assertThat(alert.status()).isEqualTo("firing");
        assertThat(alert.name()).isEqualTo("EkaHighErrorRate");
        assertThat(alert.severity()).isEqualTo("page");
        assertThat(alert.summary()).isEqualTo("More than 7.2% of requests fail with 5xx");
        assertThat(alert.annotations().get("reason")).contains("[0.31]");
        assertThat(alert.labels()).containsEntry("source", "cloudwatch");
        assertThat(alert.startsAt()).isEqualTo(Instant.parse("2026-11-13T10:00:00Z"));
    }

    @Test
    void rawDeliveryOkStatesAndOtherMessagesAreRecognised() {
        assertThat(CloudWatchAlarm.parse(ALARM)).isPresent();
        assertThat(CloudWatchAlarm.parse(ALARM.replace("\"ALARM\"", "\"OK\"")).orElseThrow().status())
                .isEqualTo("resolved");
        assertThat(CloudWatchAlarm.parse(ALARM.replace("[page] ", "")).orElseThrow().severity()).isEqualTo("unknown");
        assertThat(CloudWatchAlarm.parse("not json")).isEmpty();
        assertThat(CloudWatchAlarm.parse("{\"Type\":\"SubscriptionConfirmation\"}")).isEmpty();
    }

    @Test
    void onlyFiringAlarmsAreDeliveredAndEveryMessageIsDeleted() {
        List<String> deleted = new ArrayList<>();
        SqsClient sqs = new SqsClient() {
            @Override
            public ReceiveMessageResponse receiveMessage(ReceiveMessageRequest request) {
                assertThat(request.waitTimeSeconds()).isEqualTo(20);
                return ReceiveMessageResponse.builder().messages(
                        Message.builder().body(envelope(ALARM)).receiptHandle("r1").build(),
                        Message.builder().body(envelope(ALARM.replace("\"ALARM\"", "\"OK\""))).receiptHandle("r2").build(),
                        Message.builder().body("garbage").receiptHandle("r3").build()).build();
            }

            @Override
            public DeleteMessageResponse deleteMessage(DeleteMessageRequest request) {
                deleted.add(request.receiptHandle());
                return DeleteMessageResponse.builder().build();
            }

            @Override
            public String serviceName() {
                return "sqs";
            }

            @Override
            public void close() {}
        };
        List<List<Alert>> delivered = new ArrayList<>();
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        ReportDelivery delivery = new ReportDelivery((TriageService) null, (ReportMailer) null, registry, 1, Duration.ZERO, d -> {}) {
            @Override
            public void deliver(Batch batch) {
                delivered.add(batch.alerts());
            }
        };

        int handed = new SqsAlarmPoller(sqs, "https://sqs/queue", delivery, Runnable::run).pollOnce();

        assertThat(handed).isEqualTo(1);
        assertThat(delivered).singleElement().satisfies(batch -> assertThat(batch.get(0).name()).isEqualTo("EkaHighErrorRate"));
        assertThat(deleted).containsExactly("r1", "r2", "r3");
        assertThat(registry.get("eka.ops.alerts.accepted").counter().count()).isEqualTo(1.0);
    }
}
