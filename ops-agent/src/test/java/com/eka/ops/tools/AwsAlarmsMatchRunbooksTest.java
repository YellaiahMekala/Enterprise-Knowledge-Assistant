package com.eka.ops.tools;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.Test;

/**
 * The CloudWatch alarms in infra/aws/alarms.tf reach the agent by name, so each name must have a
 * runbook section, and each description must start with a severity the report understands.
 */
class AwsAlarmsMatchRunbooksTest {

    private static final Path ALARMS = Path.of("../infra/aws/alarms.tf");

    @Test
    void everyAlarmHasARunbookSectionAndASeverity() throws IOException {
        String terraform = Files.readString(ALARMS);
        List<String> names = new ArrayList<>();
        Matcher m = Pattern.compile("alarm_name\\s*=\\s*\"(\\w+)\"").matcher(terraform);
        while (m.find()) {
            names.add(m.group(1));
        }
        RunbookReader runbooks = new RunbookReader(Path.of("../docs/runbooks.md"));

        assertThat(names).contains("EkaHighErrorRate", "EkaTargetDown", "EkaAlertDeliveryFailing");
        assertThat(names).allSatisfy(name -> assertThat(runbooks.sectionFor(name)).as(name).isPresent());
        assertThat(Pattern.compile("alarm_description\\s*=\\s*\"(?!\\[(page|ticket)] )").matcher(terraform).find())
                .as("a description without [page] or [ticket]")
                .isFalse();
    }
}
