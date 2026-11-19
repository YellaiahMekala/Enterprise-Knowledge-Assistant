// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.delivery;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.config.OpsProperties;
import com.eka.ops.mail.ReportMailer;
import com.eka.ops.mail.SmtpReportMailer;
import com.eka.ops.tools.ReadOnlyHttp;
import com.eka.ops.tools.RunbookReader;
import com.eka.ops.triage.TriageReport;
import com.eka.ops.triage.TriageService;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;

/**
 * Every way an accepted alert can go wrong ends in a terminal state that someone can see: a sent
 * report (a runbook one when the investigation failed), or a counted failure plus a "triage failed"
 * notice. Nothing here sleeps: the backoff is recorded, not waited.
 */
class ReportDeliveryFailureTest {

    private static final List<Alert> FIRING = List.of(new Alert(
            "firing",
            Map.of("alertname", "EkaTargetDown", "severity", "page"),
            Map.of("summary", "Prometheus cannot scrape core"),
            Instant.parse("2026-11-08T10:00:00Z")));

    private final SimpleMeterRegistry registry = new SimpleMeterRegistry();
    private final List<TriageReport> reports = new ArrayList<>();
    private final List<String> notices = new ArrayList<>();

    private static OpsProperties properties() {
        return new OpsProperties(
                "t", "http://prometheus", "http://core", "http://edge", null, null, null,
                Path.of("../docs/runbooks.md"), 5, Duration.ofSeconds(1), null, null);
    }

    private static TriageService service(ChatModel model) {
        OpsProperties properties = properties();
        return new TriageService(
                properties, model, new ReadOnlyHttp(Duration.ofSeconds(1)), new RunbookReader(properties.runbookFile()));
    }

    /** Sends reports and notices unless told to fail. */
    private ReportMailer mailer(boolean reportsWork, boolean noticesWork) {
        return new ReportMailer() {
            @Override
            public void send(TriageReport report) {
                if (!reportsWork) {
                    throw new MailSendException("smtp down");
                }
                reports.add(report);
            }

            @Override
            public void sendNotice(String subject, String body) {
                if (!noticesWork) {
                    throw new MailSendException("smtp down");
                }
                notices.add(subject + "\n" + body);
            }
        };
    }

    private ReportDelivery delivery(TriageService triage, ReportMailer mailer, Duration timeout, Path journal) {
        return new ReportDelivery(triage, mailer, registry, 3, Duration.ofSeconds(5), d -> {}, timeout, journal);
    }

    private double count(String name) {
        return registry.get(name).counter().count();
    }

    private double pending() {
        return registry.get("eka.ops.reports.pending").gauge().value();
    }

    /** A model that is down: every call throws. */
    private static ChatModel modelDown() {
        return new ChatModel() {
            @Override
            public ChatResponse doChat(ChatRequest request) {
                throw new IllegalStateException("503 service unavailable");
            }
        };
    }

    @Test
    void aModelThatIsDownGivesARunbookReportNotALostAlert() {
        ReportDelivery delivery = delivery(service(modelDown()), mailer(true, true), null, null);

        delivery.deliver(delivery.accepted(FIRING));

        assertThat(reports).singleElement().satisfies(report -> {
            assertThat(report.aiAssisted()).isFalse();
            assertThat(report.note()).contains("model call failed");
        });
        assertThat(count("eka.ops.reports.sent")).isEqualTo(1);
        assertThat(count("eka.ops.reports.fallback")).isEqualTo(1);
        assertThat(count("eka.ops.reports.failed")).isZero();
        assertThat(pending()).isZero();
    }

    @Test
    void anInvestigationThatHangsIsCutOffAndReportedFromTheRunbook() {
        CountDownLatch never = new CountDownLatch(1);
        TriageService hanging = new TriageService(properties(), null, null, new RunbookReader(Path.of("../docs/runbooks.md")), null) {
            @Override
            public TriageReport triage(List<Alert> alerts) {
                try {
                    never.await();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                return null;
            }
        };
        ReportDelivery delivery = delivery(hanging, mailer(true, true), Duration.ofMillis(200), null);

        delivery.deliver(delivery.accepted(FIRING));

        assertThat(reports).singleElement().satisfies(report -> {
            assertThat(report.aiAssisted()).isFalse();
            assertThat(report.note()).contains("did not finish within");
        });
        assertThat(count("eka.ops.reports.sent")).isEqualTo(1);
        assertThat(count("eka.ops.reports.fallback")).isEqualTo(1);
        assertThat(pending()).isZero();
    }

    @Test
    void aTriageThatThrowsIsStillReportedFromTheRunbook() {
        TriageService broken = new TriageService(properties(), null, null, new RunbookReader(Path.of("../docs/runbooks.md")), null) {
            @Override
            public TriageReport triage(List<Alert> alerts) {
                throw new IllegalStateException("a bug in the agent");
            }
        };
        ReportDelivery delivery = delivery(broken, mailer(true, true), Duration.ofSeconds(5), null);

        delivery.deliver(delivery.accepted(FIRING));

        assertThat(reports).singleElement().satisfies(report -> assertThat(report.note()).contains("IllegalStateException"));
        assertThat(count("eka.ops.reports.sent")).isEqualTo(1);
        assertThat(pending()).isZero();
    }

    @Test
    void whenEvenTheRunbookReportFailsAFailureNoticeGoesOut() {
        TriageService nothingWorks = new TriageService(properties(), null, null, new RunbookReader(Path.of("../docs/runbooks.md")), null) {
            @Override
            public TriageReport triage(List<Alert> alerts) {
                throw new IllegalStateException("a bug in the agent");
            }

            @Override
            public TriageReport runbookOnly(List<Alert> alerts, String note) {
                throw new IllegalStateException("the runbook is unreadable");
            }
        };
        ReportDelivery delivery = delivery(nothingWorks, mailer(true, true), null, null);

        delivery.deliver(delivery.accepted(FIRING));

        assertThat(reports).isEmpty();
        assertThat(notices).singleElement().satisfies(notice -> assertThat(notice)
                .contains("triage failed: EkaTargetDown")
                .contains("no report could be built")
                .contains("still active in Alertmanager"));
        assertThat(count("eka.ops.reports.failed")).isEqualTo(1);
        assertThat(count("eka.ops.notices.sent")).isEqualTo(1);
        assertThat(count("eka.ops.reports.sent")).isZero();
        assertThat(pending()).isZero();
    }

    @Test
    void aReportThatCannotBeEmailedEndsFailedWithANotice() {
        ReportDelivery delivery = delivery(service(modelDown()), mailer(false, true), null, null);

        delivery.deliver(delivery.accepted(FIRING));

        assertThat(reports).isEmpty();
        assertThat(notices).singleElement().satisfies(notice -> assertThat(notice)
                .contains("triage failed: EkaTargetDown")
                .contains("could not be emailed"));
        assertThat(count("eka.ops.reports.failed")).isEqualTo(1);
        assertThat(count("eka.ops.notices.sent")).isEqualTo(1);
        assertThat(pending()).isZero();
    }

    @Test
    void whenMailIsFullyDownTheFailureIsCountedForPrometheusToAlertOn() {
        ReportDelivery delivery = delivery(service(modelDown()), mailer(false, false), null, null);

        delivery.deliver(delivery.accepted(FIRING));

        assertThat(count("eka.ops.alerts.accepted")).isEqualTo(1);
        assertThat(count("eka.ops.reports.sent")).isZero();
        assertThat(count("eka.ops.reports.failed")).isEqualTo(1);
        assertThat(count("eka.ops.notices.sent")).isZero();
        assertThat(pending()).isZero();
    }

    @Test
    void everyAcceptedBatchEndsInExactlyOneTerminalState() {
        boolean[] reportsWork = {true};
        ReportMailer flaky = new ReportMailer() {
            @Override
            public void send(TriageReport report) {
                if (!reportsWork[0]) {
                    throw new MailSendException("smtp down");
                }
            }

            @Override
            public void sendNotice(String subject, String body) {
                throw new MailSendException("smtp down");
            }
        };
        ReportDelivery delivery = delivery(service(modelDown()), flaky, null, null);

        delivery.deliver(delivery.accepted(FIRING));
        reportsWork[0] = false;
        delivery.deliver(delivery.accepted(FIRING));
        delivery.deliver(delivery.accepted(FIRING));

        assertThat(count("eka.ops.alerts.accepted")).isEqualTo(3);
        assertThat(count("eka.ops.reports.sent") + count("eka.ops.reports.failed")).isEqualTo(3);
        assertThat(pending()).isZero();
    }

    @Test
    void anAcceptedBatchIsJournaledUntilItIsFinished(@TempDir Path journal) throws Exception {
        CountDownLatch release = new CountDownLatch(1);
        CountDownLatch started = new CountDownLatch(1);
        TriageService slow = new TriageService(properties(), null, null, new RunbookReader(Path.of("../docs/runbooks.md")), null) {
            @Override
            public TriageReport triage(List<Alert> alerts) {
                started.countDown();
                try {
                    release.await();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                return runbookOnly(alerts, "slow");
            }
        };
        ReportDelivery delivery = delivery(slow, mailer(true, true), null, journal);

        ReportDelivery.Batch batch = delivery.accepted(FIRING);
        Thread worker = Thread.ofVirtual().start(() -> delivery.deliver(batch));
        started.await();
        assertThat(files(journal)).hasSize(1);

        release.countDown();
        worker.join(5_000);
        assertThat(files(journal)).isEmpty();
        assertThat(reports).hasSize(1);
    }

    @Test
    void aBatchInterruptedByARestartIsFinishedAtStartUp(@TempDir Path journal) throws Exception {
        // First process: accepts the alert, then dies before delivering (deliver is never called).
        new ReportDelivery(service(null), mailer(true, true), new SimpleMeterRegistry(), 3, Duration.ofSeconds(5), d -> {}, null, journal)
                .accepted(FIRING);
        assertThat(files(journal)).hasSize(1);

        // Second process: same journal directory.
        ReportDelivery restarted = delivery(service(null), mailer(true, true), null, journal);
        int handed = restarted.recover(Runnable::run);

        assertThat(handed).isEqualTo(1);
        assertThat(reports).singleElement().satisfies(report -> {
            assertThat(report.alerts()).singleElement().satisfies(alert -> {
                assertThat(alert.name()).isEqualTo("EkaTargetDown");
                assertThat(alert.startsAt()).isEqualTo(Instant.parse("2026-11-08T10:00:00Z"));
            });
        });
        assertThat(count("eka.ops.alerts.recovered")).isEqualTo(1);
        assertThat(count("eka.ops.reports.sent")).isEqualTo(1);
        assertThat(files(journal)).isEmpty();
        assertThat(pending()).isZero();
    }

    @Test
    void aCorruptJournalFileIsMovedAsideNotRetriedForever(@TempDir Path journal) throws Exception {
        Files.writeString(journal.resolve("bad.json"), "not json");
        ReportDelivery delivery = delivery(service(null), mailer(true, true), null, journal);

        assertThat(delivery.recover(Runnable::run)).isZero();
        assertThat(delivery.recover(Runnable::run)).isZero();

        assertThat(journal.resolve("bad.json.corrupt")).exists();
        assertThat(journal.resolve("bad.json")).doesNotExist();
        assertThat(reports).isEmpty();
        assertThat(pending()).isZero();
    }

    @Test
    void aMissingRecipientCountsAsFailedInsteadOfLookingSent() {
        JavaMailSender sender = mock(JavaMailSender.class);
        SmtpReportMailer smtp = new SmtpReportMailer(sender, new OpsProperties.Mail("", ""));
        ReportDelivery delivery = delivery(service(null), smtp, null, null);

        delivery.deliver(delivery.accepted(FIRING));

        assertThat(count("eka.ops.reports.sent")).isZero();
        assertThat(count("eka.ops.reports.failed")).isEqualTo(1);
        org.mockito.Mockito.verifyNoInteractions(sender);
    }

    @Test
    void theNoticeIsAPlainMailToTheConfiguredRecipient() {
        JavaMailSender sender = mock(JavaMailSender.class);
        SmtpReportMailer smtp = new SmtpReportMailer(sender, new OpsProperties.Mail("oncall@example.test", "eka@example.test"));

        smtp.sendNotice("[EKA] triage failed: X", "body");

        org.mockito.ArgumentCaptor<SimpleMailMessage> message = org.mockito.ArgumentCaptor.forClass(SimpleMailMessage.class);
        verify(sender).send(message.capture());
        assertThat(message.getValue().getSubject()).isEqualTo("[EKA] triage failed: X");
        assertThat(message.getValue().getTo()).containsExactly("oncall@example.test");
        assertThatThrownBy(() -> new SmtpReportMailer(sender, null).sendNotice("s", "b"))
                .isInstanceOf(IllegalStateException.class);
        org.mockito.Mockito.verify(sender, org.mockito.Mockito.times(1)).send(any(SimpleMailMessage.class));
    }

    private static List<Path> files(Path dir) throws Exception {
        try (Stream<Path> list = Files.list(dir)) {
            return list.filter(f -> f.getFileName().toString().endsWith(".json")).toList();
        }
    }
}
