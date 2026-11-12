package com.eka.ops.delivery;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.config.OpsProperties;
import com.eka.ops.mail.ReportMailer;
import com.eka.ops.tools.ReadOnlyHttp;
import com.eka.ops.tools.RunbookReader;
import com.eka.ops.triage.TriageReport;
import com.eka.ops.triage.TriageService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.springframework.mail.MailSendException;

/** An accepted alert ends in a sent report, or in a counted failure (no model, runbook only). */
class ReportDeliveryTest {

    private static final List<Alert> FIRING = List.of(new Alert(
            "firing",
            Map.of("alertname", "EkaTargetDown", "severity", "page"),
            Map.of("summary", "Prometheus cannot scrape core"),
            null));

    private final SimpleMeterRegistry registry = new SimpleMeterRegistry();
    private final List<Duration> waits = new ArrayList<>();
    private final List<TriageReport> sent = new ArrayList<>();

    private static TriageService runbookTriage() {
        OpsProperties properties = new OpsProperties(
                "t", "http://prometheus", "http://core", "http://edge", null, null,
                Path.of("../docs/runbooks.md"), 5, Duration.ofSeconds(1), null, null);
        return new TriageService(
                properties, null, new ReadOnlyHttp(Duration.ofSeconds(1)), new RunbookReader(properties.runbookFile()));
    }

    /** Fails the first {@code failures} sends, then succeeds. */
    private ReportMailer mailerFailing(int failures) {
        int[] left = {failures};
        return report -> {
            if (left[0]-- > 0) {
                throw new MailSendException("connection refused");
            }
            sent.add(report);
        };
    }

    private ReportDelivery delivery(TriageService triage, ReportMailer mailer) {
        return new ReportDelivery(triage, mailer, registry, 3, Duration.ofSeconds(5), waits::add);
    }

    private double count(String name) {
        return registry.get(name).counter().count();
    }

    @Test
    void aReportIsSentAndCounted() {
        ReportDelivery delivery = delivery(runbookTriage(), mailerFailing(0));
        delivery.accepted();
        assertThat(delivery.pending()).isEqualTo(1);

        delivery.deliver(FIRING);

        assertThat(sent).hasSize(1);
        assertThat(count("eka.ops.alerts.accepted")).isEqualTo(1);
        assertThat(count("eka.ops.reports.sent")).isEqualTo(1);
        assertThat(count("eka.ops.reports.failed")).isZero();
        assertThat(delivery.pending()).isZero();
        assertThat(waits).isEmpty();
    }

    @Test
    void aMailFailureIsRetriedWithBackoff() {
        ReportDelivery delivery = delivery(runbookTriage(), mailerFailing(2));
        delivery.accepted();
        delivery.deliver(FIRING);

        assertThat(sent).hasSize(1);
        assertThat(waits).containsExactly(Duration.ofSeconds(5), Duration.ofSeconds(10));
        assertThat(count("eka.ops.reports.failed")).isZero();
    }

    @Test
    void aReportThatCannotBeSentIsCountedAsFailedNotLost() {
        ReportDelivery delivery = delivery(runbookTriage(), mailerFailing(99));
        delivery.accepted();
        delivery.deliver(FIRING);

        assertThat(sent).isEmpty();
        assertThat(waits).hasSize(2);
        assertThat(count("eka.ops.reports.failed")).isEqualTo(1);
        assertThat(count("eka.ops.reports.sent")).isZero();
        assertThat(delivery.pending()).isZero();
    }

    @Test
    void anUnexpectedTriageErrorStillSendsARunbookReport() {
        TriageService broken = new TriageService(
                null, null, null, new RunbookReader(Path.of("../docs/runbooks.md")), null) {
            @Override
            public TriageReport triage(List<Alert> alerts) {
                throw new IllegalStateException("a bug");
            }
        };
        ReportDelivery delivery = delivery(broken, mailerFailing(0));
        delivery.accepted();
        delivery.deliver(FIRING);

        assertThat(sent).hasSize(1);
        assertThat(sent.get(0).aiAssisted()).isFalse();
        assertThat(sent.get(0).note()).contains("IllegalStateException");
    }

    @Test
    void aBatchStillBeingInvestigatedIsPending() throws Exception {
        CountDownLatch release = new CountDownLatch(1);
        TriageService slow = new TriageService(null, null, null, new RunbookReader(Path.of("../docs/runbooks.md")), null) {
            @Override
            public TriageReport triage(List<Alert> alerts) {
                try {
                    release.await(5, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                return runbookOnly(alerts, "slow");
            }
        };
        ReportDelivery delivery = delivery(slow, mailerFailing(0));
        delivery.accepted();
        Thread worker = Thread.ofVirtual().start(() -> delivery.deliver(FIRING));

        assertThat(registry.get("eka.ops.reports.pending").gauge().value()).isEqualTo(1.0);
        release.countDown();
        worker.join(5_000);
        assertThat(registry.get("eka.ops.reports.pending").gauge().value()).isZero();
    }
}
