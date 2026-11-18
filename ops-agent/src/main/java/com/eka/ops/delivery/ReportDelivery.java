package com.eka.ops.delivery;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.mail.ReportMailer;
import com.eka.ops.triage.TriageReport;
import com.eka.ops.triage.TriageService;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Stream;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;
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
 *
 * <p>Every failure path ends in one of two states. A model error, a missing model or a hung
 * investigation (bounded by a timeout) gives a runbook report. A triage that cannot even do that,
 * or a report that cannot be sent, is counted as failed and also tried as a short "triage failed"
 * notice. When a journal directory is set, an accepted batch is written to a file before the 202
 * and removed at its terminal state, so {@link #recover} can finish batches a restart interrupted.
 */
public class ReportDelivery {

    private static final Logger log = LoggerFactory.getLogger(ReportDelivery.class);

    /** Waits between attempts; replaced in tests so they do not sleep. */
    @FunctionalInterface
    public interface Sleeper {
        void sleep(Duration duration) throws InterruptedException;
    }

    /** An accepted batch: its journal id and its alerts. */
    public record Batch(String id, List<Alert> alerts) {}

    private final TriageService triage;
    private final ReportMailer mailer;
    private final int attempts;
    private final Duration backoff;
    private final Sleeper sleeper;
    private final Duration investigationTimeout;
    private final Path journal;
    private final Counter accepted;
    private final Counter sent;
    private final Counter failed;
    private final Counter fallback;
    private final Counter notices;
    private final Counter recovered;
    private final AtomicInteger pending = new AtomicInteger();
    private final JsonMapper json = JsonMapper.builder().build();

    /** No investigation timeout and no journal. */
    public ReportDelivery(
            TriageService triage, ReportMailer mailer, MeterRegistry registry, int attempts, Duration backoff, Sleeper sleeper) {
        this(triage, mailer, registry, attempts, backoff, sleeper, null, null);
    }

    /**
     * @param investigationTimeout longest the investigation may run before the runbook report is used; null for none
     * @param journal directory for in-flight batches; null to keep them in memory only
     */
    public ReportDelivery(
            TriageService triage,
            ReportMailer mailer,
            MeterRegistry registry,
            int attempts,
            Duration backoff,
            Sleeper sleeper,
            Duration investigationTimeout,
            Path journal) {
        this.triage = triage;
        this.mailer = mailer;
        this.attempts = Math.max(1, attempts);
        this.backoff = backoff;
        this.sleeper = sleeper;
        this.investigationTimeout = investigationTimeout;
        this.journal = journal;
        this.accepted = Counter.builder("eka.ops.alerts.accepted")
                .description("Alert batches the agent accepted")
                .register(registry);
        this.sent = Counter.builder("eka.ops.reports.sent")
                .description("Triage reports emailed")
                .register(registry);
        this.failed = Counter.builder("eka.ops.reports.failed")
                .description("Accepted alert batches whose report could not be emailed after all attempts")
                .register(registry);
        this.fallback = Counter.builder("eka.ops.reports.fallback")
                .description("Reports built from the runbook alone: no model, a model error or a timeout")
                .register(registry);
        this.notices = Counter.builder("eka.ops.notices.sent")
                .description("Short 'triage failed' notices emailed when no report could be sent")
                .register(registry);
        this.recovered = Counter.builder("eka.ops.alerts.recovered")
                .description("Accepted batches found in the journal at start-up and finished")
                .register(registry);
        registry.gauge("eka.ops.reports.pending", pending);
    }

    /** Called on the request thread, before the 202, so an accepted batch is always counted and journaled. */
    public Batch accepted(List<Alert> firing) {
        accepted.increment();
        pending.incrementAndGet();
        Batch batch = new Batch(UUID.randomUUID().toString(), firing);
        write(batch);
        return batch;
    }

    /** Called in the background for a batch that {@link #accepted} counted. */
    public void deliver(Batch batch) {
        List<Alert> firing = batch.alerts();
        try {
            TriageReport report = null;
            try {
                report = investigate(firing);
            } catch (RuntimeException e) {
                // triage() already falls back to the runbook on model errors; this is a bug guard.
                log.error("triage failed unexpectedly: {}", e.getClass().getSimpleName());
                try {
                    report = triage.runbookOnly(firing, "The investigation failed (" + e.getClass().getSimpleName() + ").");
                } catch (RuntimeException again) {
                    log.error("the runbook report failed too: {}", again.getClass().getSimpleName());
                }
            }
            if (report == null) {
                failedWithNotice(firing, "no report could be built");
            } else {
                if (!report.aiAssisted()) {
                    fallback.increment();
                }
                TriageReport toSend = report;
                if (retry(() -> mailer.send(toSend), "sending the report")) {
                    sent.increment();
                } else {
                    failedWithNotice(firing, "the report could not be emailed");
                }
            }
        } catch (RuntimeException | Error e) {
            // Last guard: whatever went wrong, the batch ends counted as failed, never silently.
            failed.increment();
            log.error("delivery of {} alert(s) ended in {}; EkaTriageReportFailed will fire", firing.size(), e.getClass().getSimpleName());
        } finally {
            remove(batch);
            pending.decrementAndGet();
        }
    }

    /** Runs the triage under the timeout; on a timeout the runbook report is used so the alert still ends in an email. */
    private TriageReport investigate(List<Alert> firing) {
        if (investigationTimeout == null) {
            return triage.triage(firing);
        }
        CompletableFuture<TriageReport> run = new CompletableFuture<>();
        Thread worker = Thread.ofVirtual().name("triage").start(() -> {
            try {
                run.complete(triage.triage(firing));
            } catch (Throwable t) {
                run.completeExceptionally(t);
            }
        });
        try {
            return run.get(investigationTimeout.toMillis(), TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            worker.interrupt();
            log.warn("the investigation passed {} s; using the runbook report", investigationTimeout.toSeconds());
            return triage.runbookOnly(
                    firing, "The investigation did not finish within " + investigationTimeout.toSeconds() + " s.");
        } catch (InterruptedException e) {
            worker.interrupt();
            Thread.currentThread().interrupt();
            throw new IllegalStateException("interrupted", e);
        } catch (ExecutionException e) {
            Throwable cause = e.getCause();
            throw cause instanceof RuntimeException re ? re : new IllegalStateException(cause);
        }
    }

    /** The batch is failed (counted, alerting); a short notice is also tried, in case only the report was the problem. */
    private void failedWithNotice(List<Alert> alerts, String why) {
        failed.increment();
        log.error("triage report for {} alert(s) was not sent; EkaTriageReportFailed will fire", alerts.size());
        String names = String.join(", ", alerts.stream().map(Alert::name).distinct().toList());
        String body = "The triage agent accepted these alerts but " + why + ": " + names + "\n\n"
                + "The original alerts are still active in Alertmanager. Work them from docs/runbooks.md directly.\n";
        if (retry(() -> mailer.sendNotice("[EKA] triage failed: " + names, body), "sending the failure notice")) {
            notices.increment();
        }
    }

    private boolean retry(Runnable action, String what) {
        Duration wait = backoff;
        for (int attempt = 1; attempt <= attempts; attempt++) {
            try {
                action.run();
                return true;
            } catch (RuntimeException e) {
                log.warn("{} failed (attempt {} of {}): {}", what, attempt, attempts, e.getClass().getSimpleName());
                if (attempt == attempts) {
                    return false;
                }
                try {
                    sleeper.sleep(wait);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    return false;
                }
                wait = wait.multipliedBy(2);
            }
        }
        return false;
    }

    /**
     * Finishes batches a restart interrupted: reads each journal file, counts it as recovered and
     * hands it to {@code executor}. Call once at start-up. A file that cannot be read is moved
     * aside (.corrupt) and logged, so it is not retried forever.
     */
    public int recover(Executor executor) {
        if (journal == null || !Files.isDirectory(journal)) {
            return 0;
        }
        int handed = 0;
        try (Stream<Path> files = Files.list(journal)) {
            for (Path file : files.filter(f -> f.getFileName().toString().endsWith(".json")).toList()) {
                try {
                    List<Alert> alerts = json.readValue(Files.readAllBytes(file), new TypeReference<List<Alert>>() {});
                    String name = file.getFileName().toString();
                    Batch batch = new Batch(name.substring(0, name.length() - 5), alerts);
                    recovered.increment();
                    pending.incrementAndGet();
                    executor.execute(() -> deliver(batch));
                    handed++;
                } catch (IOException | RuntimeException e) {
                    log.error("journal file {} is unreadable ({}); moved aside", file.getFileName(), e.getClass().getSimpleName());
                    try {
                        Files.move(file, file.resolveSibling(file.getFileName() + ".corrupt"));
                    } catch (IOException ignored) {
                        // left in place; the next start logs it again
                    }
                }
            }
        } catch (IOException e) {
            log.error("cannot list the journal directory: {}", e.getClass().getSimpleName());
        }
        if (handed > 0) {
            log.warn("recovered {} accepted batch(es) interrupted by a restart", handed);
        }
        return handed;
    }

    private void write(Batch batch) {
        if (journal == null) {
            return;
        }
        try {
            Files.createDirectories(journal);
            Path tmp = journal.resolve(batch.id() + ".tmp");
            Files.write(tmp, json.writeValueAsBytes(batch.alerts()));
            Files.move(tmp, journal.resolve(batch.id() + ".json"), StandardCopyOption.ATOMIC_MOVE);
        } catch (IOException | RuntimeException e) {
            // Not fatal: the batch is still delivered; only a restart could lose it.
            log.warn("cannot journal a batch: {}", e.getClass().getSimpleName());
        }
    }

    private void remove(Batch batch) {
        if (journal == null) {
            return;
        }
        try {
            Files.deleteIfExists(journal.resolve(batch.id() + ".json"));
        } catch (IOException e) {
            log.warn("cannot remove a journal file: {}", e.getClass().getSimpleName());
        }
    }

    int pending() {
        return pending.get();
    }
}
