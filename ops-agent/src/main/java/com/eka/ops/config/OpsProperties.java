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
        Path runbookFile,
        @DefaultValue("5") int maxToolCalls,
        @DefaultValue("10s") Duration toolTimeout,
        Mail mail,
        Model model) {

    public record Mail(String to, String from) {}

    /** Without an api key the agent still sends a report, built from the runbook alone. */
    public record Model(String apiKey, @DefaultValue("gpt-4o-mini") String name, String baseUrl) {}
}
