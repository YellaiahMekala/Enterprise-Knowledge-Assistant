package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Path;
import org.junit.jupiter.api.Test;

/** Runs against the real docs/runbooks.md, so a renamed alert or heading breaks this test. */
class RunbookReaderTest {

    private final RunbookReader reader = new RunbookReader(Path.of("../docs/runbooks.md"));

    @Test
    void returnsTheSectionForAnAlertUpToTheNextHeading() {
        String section = reader.sectionFor("EkaEdgeCircuitOpen").orElseThrow();
        assertThat(section).contains("circuit breaker").contains("Tuning variables");
        assertThat(section).doesNotContain("## ").doesNotContain("Backup and restore");
    }

    @Test
    void everyAlertInTheRulesFileHasARunbookSection() throws Exception {
        String rules = java.nio.file.Files.readString(Path.of("../monitoring/alerts.yml"));
        var alerts = java.util.regex.Pattern.compile("- alert: (\\w+)").matcher(rules).results().map(m -> m.group(1)).toList();
        assertThat(alerts).isNotEmpty();
        for (String alert : alerts) {
            assertThat(reader.sectionFor(alert)).as("runbook for " + alert).isPresent();
        }
    }

    @Test
    void unknownAndSuspiciousNamesGiveNothing() {
        assertThat(reader.sectionFor("NoSuchAlert")).isEmpty();
        assertThat(reader.sectionFor("../../etc/passwd")).isEmpty();
        assertThat(reader.sectionFor("Eka.*")).isEmpty();
        assertThat(reader.sectionFor(null)).isEmpty();
    }

    @Test
    void aMissingFileGivesNothingInsteadOfFailing() {
        assertThat(new RunbookReader(Path.of("no-such-file.md")).sectionFor("EkaHighErrorRate")).isEmpty();
    }
}
