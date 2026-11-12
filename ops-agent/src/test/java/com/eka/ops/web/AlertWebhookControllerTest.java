package com.eka.ops.web;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.eka.ops.mail.ReportFormatter;
import com.eka.ops.mail.ReportMailer;
import com.eka.ops.triage.TriageReport;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(properties = {
    "ops.webhook-token=test-token-0123456789",
    "ops.runbook-file=../docs/runbooks.md",
    "ops.model.api-key=",
})
@AutoConfigureMockMvc
class AlertWebhookControllerTest {

    private static final String FIRING = """
            {"version":"4","status":"firing","receiver":"ops-agent","groupKey":"x",
             "alerts":[{"status":"firing",
               "labels":{"alertname":"EkaTargetDown","severity":"page","job":"core"},
               "annotations":{"summary":"Prometheus cannot scrape core"},
               "startsAt":"2026-11-08T10:00:00Z","endsAt":"0001-01-01T00:00:00Z",
               "generatorURL":"http://prometheus:9090/graph","fingerprint":"abc"}]}
            """;

    private static final String RESOLVED = FIRING.replace("\"alerts\":[{\"status\":\"firing\"", "\"alerts\":[{\"status\":\"resolved\"");

    @Autowired
    MockMvc mvc;

    @MockitoBean
    ReportMailer mailer;

    private org.springframework.test.web.servlet.ResultActions send(String token, String body) throws Exception {
        var request = post("/alerts").contentType(MediaType.APPLICATION_JSON).content(body);
        if (token != null) {
            request = request.header("Authorization", "Bearer " + token);
        }
        return mvc.perform(request);
    }

    @Test
    void withoutATokenTheAnswerIs401AndNothingIsSent() throws Exception {
        send(null, FIRING).andExpect(status().isUnauthorized());
        verify(mailer, never()).send(any());
    }

    @Test
    void aWrongTokenIs401() throws Exception {
        send("wrong-token", FIRING).andExpect(status().isUnauthorized());
        verify(mailer, never()).send(any());
    }

    @Test
    void aFiringAlertIsAcceptedAndAReportIsEmailed() throws Exception {
        send("test-token-0123456789", FIRING).andExpect(status().isAccepted());

        ArgumentCaptor<TriageReport> report = ArgumentCaptor.forClass(TriageReport.class);
        verify(mailer, timeout(5_000)).send(report.capture());
        assertThat(ReportFormatter.subject(report.getValue())).isEqualTo("[EKA PAGE] EkaTargetDown");
        assertThat(report.getValue().aiAssisted()).as("no model key in this test").isFalse();
    }

    @Test
    void resolvedAlertsAreAcknowledgedWithoutAReport() throws Exception {
        send("test-token-0123456789", RESOLVED).andExpect(status().isAccepted());
        verify(mailer, never()).send(any());
    }

    @Test
    void theDeliveryCountsAreServedForPrometheus() throws Exception {
        send("test-token-0123456789", FIRING).andExpect(status().isAccepted());
        verify(mailer, timeout(5_000)).send(any());

        String body = mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get(
                        "/actuator/prometheus"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        assertThat(body)
                .contains("eka_ops_alerts_accepted_total")
                .contains("eka_ops_reports_sent_total")
                .contains("eka_ops_reports_failed_total")
                .contains("eka_ops_reports_pending");
    }

    @Test
    void aBodyThatIsNotJsonIs400() throws Exception {
        send("test-token-0123456789", "not json").andExpect(status().isBadRequest());
    }

    @Test
    void theServiceRefusesToStartWithoutAToken() {
        var properties = new com.eka.ops.config.OpsProperties(
                " ", "http://p", "http://c", "http://e", null, null, java.nio.file.Path.of("x"), 3, java.time.Duration.ofSeconds(1), null, null);
        org.assertj.core.api.Assertions.assertThatThrownBy(
                        () -> new AlertWebhookController(properties, null, Runnable::run))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("OPS_AGENT_WEBHOOK_TOKEN");
    }
}
