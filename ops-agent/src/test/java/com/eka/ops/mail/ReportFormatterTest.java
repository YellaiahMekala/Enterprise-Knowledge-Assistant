package com.eka.ops.mail;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.triage.Triage;
import com.eka.ops.triage.TriageReport;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ReportFormatterTest {

    private static Alert alert(String name, String severity) {
        return new Alert("firing", Map.of("alertname", name, "severity", severity), Map.of("summary", "s"), Instant.parse("2026-11-08T10:00:00Z"));
    }

    private static TriageReport report(boolean ai, String note, Alert... alerts) {
        Triage triage = new Triage("Core is down", "Database unreachable", List.of("up{job=core} = 0"), List.of("Check the db"));
        return new TriageReport(List.of(alerts), triage, ai, ai ? 2 : 0, note);
    }

    @Test
    void thePageSeverityAndAlertNamesAreInTheSubject() {
        assertThat(ReportFormatter.subject(report(true, "", alert("EkaTargetDown", "page"), alert("EkaSearchSlow", "ticket"))))
                .isEqualTo("[EKA PAGE] EkaTargetDown, EkaSearchSlow");
        assertThat(ReportFormatter.subject(report(true, "", alert("EkaSearchSlow", "ticket")))).isEqualTo("[EKA ticket] EkaSearchSlow");
    }

    @Test
    void theBodyHasEvidenceStepsAndSaysTheAgentChangedNothing() {
        String body = ReportFormatter.body(report(true, "", alert("EkaTargetDown", "page")));

        assertThat(body)
                .contains("Likely cause\nDatabase unreachable")
                .contains("Evidence\n- up{job=core} = 0")
                .contains("the agent changed nothing")
                .contains("model-assisted, 2 read-only tool call(s)")
                .contains("A model can be wrong");
    }

    @Test
    void aFallbackReportSaysWhyItIsRunbookOnly() {
        String body = ReportFormatter.body(report(false, "No model is configured.", alert("EkaTargetDown", "page")));

        assertThat(body).contains("runbook only").contains("No model is configured.");
    }
}
