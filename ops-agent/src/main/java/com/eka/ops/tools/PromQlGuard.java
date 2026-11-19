// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import java.util.regex.Pattern;

/**
 * Checks a PromQL expression the model wrote before it is sent. Prometheus' query endpoint cannot
 * change anything, so this is about keeping the model on topic and the queries cheap: a short
 * expression, plain characters, and only the metric families this system exports.
 */
final class PromQlGuard {

    static final int MAX_LENGTH = 300;
    private static final Pattern CHARACTERS = Pattern.compile("[A-Za-z0-9_:.,(){}\\[\\]=~!\"'<>+\\-*/% |]+");
    private static final Pattern METRIC = Pattern.compile(
            "\\b(eka_[a-z_]+|up|resilience4j_[a-z_]+|http_server_requests_[a-z_]+|jvm_[a-z_]+|process_[a-z_]+)\\b");

    private PromQlGuard() {}

    /** Returns null when the query is acceptable, otherwise the reason it is not. */
    static String problem(String query) {
        if (query == null || query.isBlank()) {
            return "the query is empty";
        }
        if (query.length() > MAX_LENGTH) {
            return "the query is longer than " + MAX_LENGTH + " characters";
        }
        if (!CHARACTERS.matcher(query).matches()) {
            return "the query contains characters outside plain PromQL";
        }
        if (!METRIC.matcher(query).find()) {
            return "the query must use an eka_*, up, resilience4j_*, http_server_requests_*, jvm_* or process_* metric";
        }
        return null;
    }
}
