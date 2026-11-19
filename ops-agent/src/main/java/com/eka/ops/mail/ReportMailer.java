// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.mail;

import com.eka.ops.triage.TriageReport;

public interface ReportMailer {

    void send(TriageReport report);

    /** A short plain notice, used when a report could not be sent. Throws if it cannot be sent either. */
    default void sendNotice(String subject, String body) {
        throw new UnsupportedOperationException("this mailer cannot send notices");
    }
}
