// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.mail;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.triage.Triage;
import com.eka.ops.triage.TriageReport;
import java.util.List;

/** Plain text on purpose: it reads the same in every mail client and on a phone. */
public final class ReportFormatter {

    private ReportFormatter() {}

    public static String subject(TriageReport report) {
        List<Alert> alerts = report.alerts();
        String worst = alerts.stream().anyMatch(a -> "page".equals(a.severity())) ? "PAGE" : "ticket";
        String names = String.join(", ", alerts.stream().map(Alert::name).distinct().toList());
        return "[EKA " + worst + "] " + names;
    }

    public static String body(TriageReport report) {
        Triage triage = report.triage();
        StringBuilder text = new StringBuilder();
        text.append(triage.summary()).append("\n\n");
        text.append("Likely cause\n").append(triage.likelyCause()).append("\n\n");
        text.append("Evidence\n");
        bullets(text, triage.evidence());
        text.append("\nNext steps (for a person; the agent changed nothing)\n");
        bullets(text, triage.nextSteps());
        text.append("\nAlerts\n");
        for (Alert alert : report.alerts()) {
            text.append("- ")
                    .append(alert.name())
                    .append(" [")
                    .append(alert.severity())
                    .append("] since ")
                    .append(alert.startsAt())
                    .append('\n');
        }
        text.append("\nHow this was produced: ")
                .append(report.aiAssisted() ? "model-assisted, " + report.toolCalls() + " read-only tool call(s)" : "runbook only")
                .append('\n');
        if (report.note() != null && !report.note().isBlank()) {
            text.append(report.note()).append('\n');
        }
        text.append("A model can be wrong. Check the evidence before acting.\n");
        return text.toString();
    }

    private static void bullets(StringBuilder text, List<String> lines) {
        if (lines == null || lines.isEmpty()) {
            text.append("- none\n");
            return;
        }
        for (String line : lines) {
            text.append("- ").append(line).append('\n');
        }
    }
}
