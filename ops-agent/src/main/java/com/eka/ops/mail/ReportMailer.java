package com.eka.ops.mail;

import com.eka.ops.triage.TriageReport;

public interface ReportMailer {

    void send(TriageReport report);
}
