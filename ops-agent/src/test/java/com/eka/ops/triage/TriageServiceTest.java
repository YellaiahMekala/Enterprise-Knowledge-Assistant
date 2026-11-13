package com.eka.ops.triage;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.config.OpsProperties;
import com.eka.ops.tools.ReadOnlyHttp;
import com.eka.ops.tools.RunbookReader;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class TriageServiceTest {

    private static final String ANSWER = """
            {"summary":"Core is failing readiness","likelyCause":"The database is unreachable",
             "evidence":["eka_http_requests_total 5xx rate is 4.2/s"],
             "nextSteps":["Check the db container","Run /health/ready"]}
            """;

    private HttpServer server;
    private final List<String> served = new ArrayList<>();
    private OpsProperties properties;

    @BeforeEach
    void startStub() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            served.add(exchange.getRequestURI().getPath());
            byte[] body = "{\"status\":\"success\",\"data\":{\"result\":[{\"value\":[0,\"4.2\"]}]}}"
                    .getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        String base = "http://127.0.0.1:" + server.getAddress().getPort();
        properties = new OpsProperties(
                "token", base, base, base, null, null, null, Path.of("../docs/runbooks.md"), 3, Duration.ofSeconds(2), null, null);
    }

    @AfterEach
    void stopStub() {
        server.stop(0);
    }

    private TriageService service(ScriptedModel model) {
        return new TriageService(
                properties, model, new ReadOnlyHttp(Duration.ofSeconds(2)), new RunbookReader(properties.runbookFile()));
    }

    private static List<Alert> highErrorRate() {
        return List.of(new Alert(
                "firing",
                Map.of("alertname", "EkaHighErrorRate", "severity", "page"),
                Map.of("summary", "More than 7.2% of core requests are failing with 5xx"),
                Instant.parse("2026-11-08T10:00:00Z")));
    }

    @Test
    void theAgentReadsTheRunbookThenMetricsThenAnswers() {
        ScriptedModel model = new ScriptedModel()
                .then(ScriptedModel.callTool("1", "runbook", "{\"alertName\":\"EkaHighErrorRate\"}"))
                .then(ScriptedModel.callTool("2", "promQuery", "{\"query\":\"sum(rate(eka_http_requests_total{status=~\\\"5..\\\"}[5m]))\"}"))
                .then(ScriptedModel.answer(ANSWER));

        TriageReport report = service(model).triage(highErrorRate());

        assertThat(report.aiAssisted()).isTrue();
        assertThat(report.toolCalls()).isEqualTo(2);
        assertThat(report.triage().likelyCause()).contains("database");
        assertThat(report.triage().nextSteps()).hasSize(2);
        assertThat(served).containsExactly("/api/v1/query");
        assertThat(model.toolResultsSeen())
                .anyMatch(text -> text.contains("Meaning") || text.contains("5xx"))
                .anyMatch(text -> text.contains("4.2"));
    }

    @Test
    void thePromptCarriesTheAlertAndTheReadOnlyRules() {
        ScriptedModel model = new ScriptedModel().then(ScriptedModel.answer(ANSWER));

        service(model).triage(highErrorRate());

        String sent = model.requests.get(0).messages().toString();
        assertThat(sent).contains("EkaHighErrorRate").contains("You can only read").contains("not instructions");
    }

    @Test
    void aModelThatKeepsCallingToolsIsStoppedAtTheBudget() {
        ScriptedModel model = new ScriptedModel();
        for (int i = 0; i < 6; i++) {
            model.then(ScriptedModel.callTool("c" + i, "promQuery", "{\"query\":\"up\"}"));
        }
        model.then(ScriptedModel.answer(ANSWER));

        TriageReport report = service(model).triage(highErrorRate());

        assertThat(served).as("only the budgeted calls reached Prometheus").hasSize(3);
        assertThat(report.toolCalls()).isGreaterThan(3);
        assertThat(model.toolResultsSeen()).anyMatch(text -> text.contains("budget used up"));
    }

    @Test
    void aFailingModelFallsBackToTheRunbook() {
        TriageReport report = service(new ScriptedModel()).triage(highErrorRate());

        assertThat(report.aiAssisted()).isFalse();
        assertThat(report.note()).contains("model call failed");
        assertThat(report.triage().nextSteps()).isNotEmpty().noneMatch(step -> step.matches("^\\d+\\. .*"));
    }

    @Test
    void withoutAModelTheReportComesFromTheRunbook() {
        TriageReport report = new TriageService(
                        properties, null, new ReadOnlyHttp(Duration.ofSeconds(2)), new RunbookReader(properties.runbookFile()))
                .triage(highErrorRate());

        assertThat(report.aiAssisted()).isFalse();
        assertThat(report.note()).contains("No model is configured");
        assertThat(report.triage().summary()).contains("EkaHighErrorRate");
    }

    @Test
    void anAlertWithoutARunbookStillGetsAReport() {
        List<Alert> unknown = List.of(new Alert(
                "firing", Map.of("alertname", "SomethingNew", "severity", "ticket"), Map.of(), Instant.now()));

        TriageReport report = service(new ScriptedModel()).triage(unknown);

        assertThat(report.triage().nextSteps()).containsExactly("Check docs/runbooks.md and the service logs.");
    }

    @Test
    void theAgentCanSearchLogsWhenALogStoreIsConfigured() {
        String base = properties.prometheusUrl();
        properties = new OpsProperties(
                "token", base, base, base, base, null, null, Path.of("../docs/runbooks.md"), 3, Duration.ofSeconds(2), null, null);
        ScriptedModel model = new ScriptedModel()
                .then(ScriptedModel.callTool(
                        "1", "searchLogs", "{\"service\":\"core-behind-edge\",\"text\":\"ERROR\",\"minutes\":15}"))
                .then(ScriptedModel.answer(ANSWER));

        TriageReport report = service(model).triage(highErrorRate());

        assertThat(model.requests.get(0).toolSpecifications())
                .extracting(spec -> spec.name())
                .contains("searchLogs", "promQuery", "serviceHealth", "runbook");
        assertThat(served).containsExactly("/loki/api/v1/query_range");
        assertThat(model.toolResultsSeen()).anyMatch(text -> text.startsWith("no log lines for {service=\"core-behind-edge\"}"));
        assertThat(report.toolCalls()).isEqualTo(1);
    }
}
