package com.eka.ops.mail;

import com.eka.ops.triage.TriageReport;

public interface ReportMailer {

    void send(TriageReport report);

    /** A short plain notice, used when a report could not be sent. Throws if it cannot be sent either. */
    default void sendNotice(String subject, String body) {
        throw new UnsupportedOperationException("this mailer cannot send notices");
    }
}
