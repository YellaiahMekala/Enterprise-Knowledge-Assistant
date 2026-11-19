// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.config;

import java.nio.file.Path;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** Everything the agent needs from the outside. Secrets arrive as environment variables. */
@ConfigurationProperties(prefix = "ops")
public record OpsProperties(
        String webhookToken,
        String prometheusUrl,
        String coreUrl,
        String edgeManagementUrl,
        String lokiUrl,
        CloudWatch cloudwatch,
        String alarmQueueUrl,
        Path runbookFile,
        @DefaultValue("5") int maxToolCalls,
        @DefaultValue("10s") Duration toolTimeout,
        Mail mail,
        Model model) {

    public record Mail(String to, String from) {}

    /** CloudWatch Logs instead of Loki: the log group from infra/aws; the endpoint only for a local stand-in. */
    public record CloudWatch(String logGroup, String endpointUrl) {}

    /** Without an api key the agent still sends a report, built from the runbook alone. */
    public record Model(String apiKey, @DefaultValue("gpt-4o-mini") String name, String baseUrl) {}
}
