// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class OpsToolsTest {

    private HttpServer server;
    private String base;
    private final List<String> requests = new ArrayList<>();

    @BeforeEach
    void startStub() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            requests.add(exchange.getRequestMethod() + " " + exchange.getRequestURI());
            byte[] body = "{\"status\":\"success\"}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        base = "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @AfterEach
    void stopStub() {
        server.stop(0);
    }

    private OpsTools tools(int budget) {
        return new OpsTools(
                new ReadOnlyHttp(Duration.ofSeconds(2)),
                new RunbookReader(Path.of("../docs/runbooks.md")),
                base,
                base,
                base,
                new LogSearch(new ReadOnlyHttp(Duration.ofSeconds(2)), base),
                budget);
    }

    @Test
    void aQueryIsSentAsAnEncodedGetToPrometheus() {
        String result = tools(5).promQuery("up{job=\"core\"} == 0");

        assertThat(result).startsWith("HTTP 200").contains("success");
        assertThat(requests).hasSize(1);
        assertThat(requests.get(0)).startsWith("GET /api/v1/query?query=up%7Bjob%3D%22core%22%7D");
    }

    @Test
    void aRefusedQueryNeverLeavesTheProcess() {
        String result = tools(5).promQuery("node_cpu_seconds_total");

        assertThat(result).startsWith("rejected:");
        assertThat(requests).isEmpty();
    }

    @Test
    void healthChecksBothServices() {
        String result = tools(5).serviceHealth();

        assertThat(result).contains("core /health/ready: HTTP 200").contains("edge /actuator/health: HTTP 200");
        assertThat(requests).containsExactly("GET /health/ready", "GET /actuator/health");
    }

    @Test
    void anUnreachableServiceIsReportedAsTextNotAnException() {
        server.stop(0);

        assertThat(tools(5).serviceHealth()).contains("unreachable");
    }

    @Test
    void theRunbookToolReadsTheSection() {
        assertThat(tools(5).runbook("EkaTargetDown")).contains("scraped");
        assertThat(tools(5).runbook("Nope")).startsWith("no runbook section");
    }

    @Test
    void callsBeyondTheBudgetAreRefusedAndNeverReachTheService() {
        OpsTools tools = tools(2);

        tools.promQuery("up");
        tools.promQuery("up");
        String third = tools.promQuery("up");

        assertThat(third).contains("budget used up");
        assertThat(requests).hasSize(2);
        assertThat(tools.callsUsed()).isEqualTo(3);
    }

    @Test
    void logSearchGoesToTheLogStoreAndCountsAgainstTheBudget() {
        OpsTools tools = tools(5);

        tools.searchLogs("api", "ERROR", 10);

        assertThat(requests).hasSize(1);
        assertThat(requests.get(0)).startsWith("GET /loki/api/v1/query_range?query=");
        assertThat(tools.callsUsed()).isEqualTo(1);
    }

    @Test
    void withoutALogStoreTheToolSaysSoAndCallsNothing() {
        OpsTools tools = new OpsTools(
                new ReadOnlyHttp(Duration.ofSeconds(2)),
                new RunbookReader(Path.of("../docs/runbooks.md")),
                base,
                base,
                base,
                null,
                5);

        assertThat(tools.searchLogs("api", "ERROR", 10)).contains("not configured");
        assertThat(requests).isEmpty();
    }
}
