// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.alert;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.time.Instant;
import java.util.List;
import java.util.Map;

/** The subset of Alertmanager's webhook body (version 4) that the agent uses. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record AlertmanagerPayload(String status, List<Alert> alerts) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Alert(
            String status,
            Map<String, String> labels,
            Map<String, String> annotations,
            Instant startsAt) {

        public String name() {
            return labels == null ? "unknown" : labels.getOrDefault("alertname", "unknown");
        }

        public String severity() {
            return labels == null ? "unknown" : labels.getOrDefault("severity", "unknown");
        }

        public String summary() {
            return annotations == null ? "" : annotations.getOrDefault("summary", "");
        }
    }
}
