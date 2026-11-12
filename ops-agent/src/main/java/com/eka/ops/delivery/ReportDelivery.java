package com.eka.ops.delivery;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.mail.ReportMailer;
import com.eka.ops.triage.TriageReport;
import com.eka.ops.triage.TriageService;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Makes every accepted alert end in a sent report, or in a counted failure a person hears about.
 *
 * <p>Alertmanager's watchdog only sees deliveries to the agent. Once the agent has answered 202,
 * a failing mail server or a hung investigation would otherwise end in a log line nobody reads.
 * Here each batch is counted when accepted; the email is retried with backoff; a final failure is
 * counted, and batches still in progress are a gauge. Prometheus alerts on the failure counter and
 * on a batch pending too long, and Alertmanager emails those two alerts directly, not through the
 * agent (monitoring/alertmanager.yml).
 */
public class ReportDelivery {

    private static final Logger log = LoggerFactory.getLogger(ReportDelivery.class);

    /** Waits between attempts; replaced in tests so they do not sleep. */
    @FunctionalInterface
    public interface Sleeper {
        void sleep(Duration duration) throws InterruptedException;
    }

    private final TriageService triage;
    private final ReportMailer mailer;
    private final int attempts;
    private final Duration backoff;
    private final Sleeper sleeper;
    private final Counter accepted;
    private final Counter sent;
    private final Counter failed;
    private final AtomicInteger pending = new AtomicInteger();

    public ReportDelivery(
            TriageService triage, ReportMailer mailer, MeterRegistry registry, int attempts, Duration backoff, Sleeper sleeper) {
        this.triage = triage;
        this.mailer = mailer;
        this.attempts = Math.max(1, attempts);
        this.backoff = backoff;
        this.sleeper = sleeper;
        this.accepted = Counter.builder("eka.ops.alerts.accepted")
                .description("Alert batches the agent accepted")
                .register(registry);
        this.sent = Counter.builder("eka.ops.reports.sent")
                .description("Triage reports emailed")
                .register(registry);
        this.failed = Counter.builder("eka.ops.reports.failed")
                .description("Accepted alert batches whose report could not be emailed after all attempts")
                .register(registry);
        registry.gauge("eka.ops.reports.pending", pending);
    }

    /** Called on the request thread, before the 202, so an accepted batch is always counted. */
    public void accepted() {
        accepted.increment();
        pending.incrementAndGet();
    }

    /** Called in the background for a batch that {@link #accepted()} counted. */
    public void deliver(List<Alert> firing) {
        try {
            TriageReport report;
            try {
                report = triage.triage(firing);
            } catch (RuntimeException e) {
                // triage() already falls back to the runbook on model errors; this is a bug guard.
                log.error("triage failed unexpectedly: {}", e.getClass().getSimpleName());
                report = triage.runbookOnly(firing, "The investigation failed (" + e.getClass().getSimpleName() + ").");
            }
            send(report, firing.size());
        } finally {
            pending.decrementAndGet();
        }
    }

    private void send(TriageReport report, int alerts) {
        Duration wait = backoff;
        for (int attempt = 1; attempt <= attempts; attempt++) {
            try {
                mailer.send(report);
                sent.increment();
                return;
            } catch (RuntimeException e) {
                log.warn("sending the report failed (attempt {} of {}): {}", attempt, attempts, e.getClass().getSimpleName());
                if (attempt == attempts) {
                    break;
                }
                try {
                    sleeper.sleep(wait);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    break;
                }
                wait = wait.multipliedBy(2);
            }
        }
        failed.increment();
        log.error("triage report for {} alert(s) was not sent; EkaTriageReportFailed will fire", alerts);
    }

    int pending() {
        return pending.get();
    }
}
