// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Searches recent logs. The model never writes a query: it picks a service from a fixed list, a
 * plain text to look for and a time window, and the store (Loki or CloudWatch Logs) builds the
 * query from those checked parts. Results are cut to a few short lines, and values that look like
 * credentials are masked before the model or the report sees them.
 */
public class LogSearch {

    static final Set<String> SERVICES =
            Set.of("api", "worker", "core-behind-edge", "edge", "db", "ops-agent", "prometheus", "alertmanager");
    static final int MAX_TEXT = 100;
    static final int MAX_MINUTES = 60;
    static final int MAX_LINES = 20;
    static final int MAX_LINE_CHARS = 300;

    // No quotes, backslashes or backticks, so the text cannot end the query string it goes into.
    private static final Pattern TEXT = Pattern.compile("[A-Za-z0-9 _.:/=@#%+\\-\\[\\]()]*");
    private static final Pattern SECRET = Pattern.compile(
            "(?i)(api[_-]?key|x-api-key|authorization|password|passwd|secret|token)"
                    + "(\"?\\s*[:=]\\s*\"?)(bearer\\s+)?[^\\s\"',}]+");

    private final LogStore store;

    public LogSearch(LogStore store) {
        this.store = store;
    }

    /** Loki, the store on the Compose stack. */
    public LogSearch(ReadOnlyHttp http, String lokiUrl) {
        this(new LokiLogStore(http, lokiUrl));
    }

    /** Returns null when the arguments are acceptable, otherwise the reason they are not. */
    static String problem(String service, String text, int minutes) {
        if (service == null || !SERVICES.contains(service)) {
            return "service must be one of " + SERVICES.stream().sorted().toList();
        }
        if (text != null && text.length() > MAX_TEXT) {
            return "the text is longer than " + MAX_TEXT + " characters";
        }
        if (text != null && !TEXT.matcher(text).matches()) {
            return "the text may hold only letters, digits, spaces and _.:/=@#%+-[]()";
        }
        if (minutes < 1 || minutes > MAX_MINUTES) {
            return "minutes must be between 1 and " + MAX_MINUTES;
        }
        return null;
    }

    static String redact(String line) {
        return SECRET.matcher(line).replaceAll("$1$2$3***");
    }

    public String search(String service, String text, int minutes) {
        String problem = problem(service, text, minutes);
        if (problem != null) {
            return "rejected: " + problem;
        }
        String query = store.describe(service, text);
        List<LogStore.Line> lines;
        try {
            lines = store.newest(service, text, minutes, MAX_LINES);
        } catch (LogStore.LogStoreException e) {
            return e.getMessage();
        }
        if (lines.isEmpty()) {
            return "no log lines for " + query + " in the last " + minutes + " minutes";
        }
        StringBuilder out = new StringBuilder(lines.size() + " newest line(s) for " + query + ":\n");
        for (LogStore.Line line : lines) {
            String shown = redact(line.text().strip());
            if (shown.length() > MAX_LINE_CHARS) {
                shown = shown.substring(0, MAX_LINE_CHARS) + "...";
            }
            out.append(line.time()).append(' ').append(shown).append('\n');
        }
        return out.toString();
    }
}
