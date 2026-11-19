// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import dev.langchain4j.agent.tool.P;
import dev.langchain4j.agent.tool.Tool;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * What the triage agent may do: look, never change. One instance serves one investigation, so the
 * call budget is per alert group. Every call is written to the audit logger with its arguments and
 * the size of the answer.
 */
public class OpsTools {

    private static final Logger audit = LoggerFactory.getLogger("eka.ops.audit");

    private final ReadOnlyHttp http;
    private final RunbookReader runbooks;
    private final String prometheusUrl;
    private final String coreUrl;
    private final String edgeManagementUrl;
    private final LogSearch logs;
    private final int budget;
    private final AtomicInteger used = new AtomicInteger();

    public OpsTools(
            ReadOnlyHttp http,
            RunbookReader runbooks,
            String prometheusUrl,
            String coreUrl,
            String edgeManagementUrl,
            LogSearch logs,
            int budget) {
        this.http = http;
        this.runbooks = runbooks;
        this.prometheusUrl = prometheusUrl;
        this.coreUrl = coreUrl;
        this.edgeManagementUrl = edgeManagementUrl;
        this.logs = logs;
        this.budget = budget;
    }

    public int callsUsed() {
        return used.get();
    }

    @Tool("Runs a read-only PromQL instant query against Prometheus and returns the JSON result. "
            + "Useful metrics: eka_http_requests_total{route,status}, eka_http_request_duration_seconds_bucket, "
            + "up{job}, resilience4j_circuitbreaker_state{name,state}.")
    public String promQuery(@P("PromQL expression, at most 300 characters") String query) {
        return run("promQuery", query, () -> {
            String problem = PromQlGuard.problem(query);
            if (problem != null) {
                return "rejected: " + problem;
            }
            if (prometheusUrl == null || prometheusUrl.isBlank()) {
                return "Prometheus is not deployed here; use serviceHealth, searchLogs and the alarm's reason";
            }
            return http.get(
                    prometheusUrl, "/api/v1/query?query=" + URLEncoder.encode(query, StandardCharsets.UTF_8));
        });
    }

    @Tool("Checks whether the core API is ready (database reachable) and whether the edge reports itself healthy.")
    public String serviceHealth() {
        return run("serviceHealth", "", () -> "core /health/ready: " + http.get(coreUrl, "/health/ready")
                + "\nedge /actuator/health: " + http.get(edgeManagementUrl, "/actuator/health"));
    }

    @Tool("Searches the newest container log lines in Loki (at most 20, credentials masked). "
            + "Services: api, worker, core-behind-edge, edge, db, ops-agent, prometheus, alertmanager. "
            + "Use it to find errors behind an alert. Text ERROR (or WARN, WARNING) returns warnings and "
            + "errors at any level name; other text is matched literally, for example Traceback or database.")
    public String searchLogs(
            @P("compose service name, for example core-behind-edge") String service,
            @P("plain text the line must contain (case-sensitive), may be empty; at most 100 characters") String text,
            @P("how many minutes back to look, 1 to 60") int minutes) {
        return run("searchLogs", service + " | " + text + " | " + minutes + "m", () -> logs == null
                ? "log search is not configured (no log store URL)"
                : logs.search(service, text, minutes));
    }

    @Tool("Returns the runbook section for an alert, for example EkaHighErrorRate, with the steps to follow.")
    public String runbook(@P("the alert name") String alertName) {
        return run("runbook", alertName, () -> runbooks.sectionFor(alertName)
                .orElse("no runbook section found for " + alertName));
    }

    private String run(String tool, String argument, Supplier<String> action) {
        int number = used.incrementAndGet();
        if (number > budget) {
            audit.warn("tool={} call={} refused: budget of {} calls used", tool, number, budget);
            return "tool budget used up: answer now with what you have found";
        }
        String result = action.get();
        audit.info(
                "tool={} call={} args=\"{}\" result_chars={}",
                tool,
                number,
                argument.length() > 120 ? argument.substring(0, 120) + "..." : argument,
                result.length());
        return result;
    }
}
