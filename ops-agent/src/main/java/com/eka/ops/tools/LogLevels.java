// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * A level word as the search text means "warnings and worse", not the literal word. The services
 * log at different names (Python WARNING, Spring WARN, ERROR, CRITICAL), and the core logs a
 * failing dependency such as the database at WARNING, so a literal ERROR search found nothing in
 * the live triage run of 2026-11-13 although Loki held the failure lines.
 */
final class LogLevels {

    /** Matched as substrings: WARN also covers WARNING. Constants only, never model text. */
    static final List<String> PROBLEM_TERMS = List.of("ERROR", "WARN", "CRITICAL", "FATAL");

    private static final Set<String> LEVEL_WORDS = Set.of("ERROR", "ERRORS", "WARN", "WARNING", "WARNINGS");

    private LogLevels() {}

    /** True when the text asks for problem lines by level rather than for a literal text. */
    static boolean isLevelSearch(String text) {
        return text != null && LEVEL_WORDS.contains(text.strip().toUpperCase(Locale.ROOT));
    }

    /** True when the line matches the search: any problem term for a level search, else the text. */
    static boolean matches(String line, String text) {
        if (text == null || text.isBlank()) {
            return true;
        }
        if (isLevelSearch(text)) {
            return PROBLEM_TERMS.stream().anyMatch(line::contains);
        }
        return line.contains(text.strip());
    }
}
