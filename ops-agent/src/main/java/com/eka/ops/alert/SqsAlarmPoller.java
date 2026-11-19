// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.alert;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.delivery.ReportDelivery;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.Executor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import software.amazon.awssdk.core.exception.SdkException;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.DeleteMessageRequest;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageRequest;

/**
 * On AWS the agent has no public endpoint: CloudWatch alarms go to SNS, SNS to an SQS queue, and
 * this polls the queue with the task role. Each firing alarm goes to the same {@link ReportDelivery}
 * as an Alertmanager webhook. A message is deleted once accepted (the delivery retries and counts
 * failures itself) or once it is known not to be a firing alarm; a message that keeps failing for
 * another reason is left for SQS to move to the dead-letter queue.
 */
public class SqsAlarmPoller implements Runnable {

    private static final Logger log = LoggerFactory.getLogger(SqsAlarmPoller.class);

    private final SqsClient sqs;
    private final String queueUrl;
    private final ReportDelivery delivery;
    private final Executor executor;
    private volatile boolean running = true;

    public SqsAlarmPoller(SqsClient sqs, String queueUrl, ReportDelivery delivery, Executor executor) {
        this.sqs = sqs;
        this.queueUrl = queueUrl;
        this.delivery = delivery;
        this.executor = executor;
    }

    @Override
    public void run() {
        log.info("polling {} for CloudWatch alarms", queueUrl);
        while (running) {
            try {
                pollOnce();
            } catch (SdkException e) {
                log.warn("alarm queue receive failed: {}: {}", e.getClass().getSimpleName(), e.getMessage());
                pause();
            }
        }
    }

    public void stop() {
        running = false;
    }

    /** One long poll; returns how many alarms were handed to the delivery. */
    public int pollOnce() {
        List<Message> messages = sqs.receiveMessage(ReceiveMessageRequest.builder()
                        .queueUrl(queueUrl)
                        .maxNumberOfMessages(10)
                        .waitTimeSeconds(20)
                        .build())
                .messages();
        int handed = 0;
        for (Message message : messages) {
            Optional<Alert> alert = CloudWatchAlarm.parse(message.body());
            if (alert.isEmpty()) {
                log.warn("dropped a queue message that is not a CloudWatch alarm notification");
            } else if ("firing".equals(alert.get().status())) {
                List<Alert> firing = List.of(alert.get());
                ReportDelivery.Batch batch = delivery.accepted(firing);
                executor.execute(() -> delivery.deliver(batch));
                handed++;
            }
            sqs.deleteMessage(DeleteMessageRequest.builder()
                    .queueUrl(queueUrl)
                    .receiptHandle(message.receiptHandle())
                    .build());
        }
        return handed;
    }

    private void pause() {
        try {
            Thread.sleep(5_000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            running = false;
        }
    }
}
