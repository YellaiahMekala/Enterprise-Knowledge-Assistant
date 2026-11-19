// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.tools;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Reads one alert's section out of docs/runbooks.md (a "## AlertName" heading up to the next "## "). */
public class RunbookReader {

    private final Path file;

    public RunbookReader(Path file) {
        this.file = file;
    }

    public Optional<String> sectionFor(String alertName) {
        if (alertName == null || !alertName.matches("[A-Za-z][A-Za-z0-9_]{0,60}")) {
            return Optional.empty();
        }
        String text;
        try {
            text = Files.readString(file);
        } catch (IOException e) {
            return Optional.empty();
        }
        Matcher heading = Pattern.compile("(?m)^## " + Pattern.quote(alertName) + "\\s*$").matcher(text);
        if (!heading.find()) {
            return Optional.empty();
        }
        int start = heading.end();
        Matcher next = Pattern.compile("(?m)^## ").matcher(text);
        int end = next.find(start) ? next.start() : text.length();
        return Optional.of(text.substring(start, end).strip());
    }
}
