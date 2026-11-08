package com.eka.ops.web;

import com.eka.ops.alert.AlertmanagerPayload;
import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.config.OpsProperties;
import com.eka.ops.mail.ReportMailer;
import com.eka.ops.triage.TriageReport;
import com.eka.ops.triage.TriageService;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import java.util.concurrent.Executor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/**
 * Alertmanager's webhook. It answers 202 at once and investigates in the background, so a slow
 * model never makes Alertmanager retry. Without a matching bearer token the answer is 401, and
 * the service refuses to start without a token at all.
 */
@RestController
public class AlertWebhookController {

    private static final Logger log = LoggerFactory.getLogger(AlertWebhookController.class);

    private final byte[] token;
    private final TriageService triage;
    private final ReportMailer mailer;
    private final Executor executor;

    public AlertWebhookController(OpsProperties properties, TriageService triage, ReportMailer mailer, Executor triageExecutor) {
        if (properties.webhookToken() == null || properties.webhookToken().isBlank()) {
            throw new IllegalStateException("OPS_AGENT_WEBHOOK_TOKEN must be set");
        }
        this.token = properties.webhookToken().getBytes(StandardCharsets.UTF_8);
        this.triage = triage;
        this.mailer = mailer;
        this.executor = triageExecutor;
    }

    @PostMapping("/alerts")
    public ResponseEntity<Void> receive(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody AlertmanagerPayload payload) {
        if (!tokenMatches(authorization)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }
        List<Alert> firing = payload.alerts() == null
                ? List.of()
                : payload.alerts().stream().filter(a -> "firing".equals(a.status())).toList();
        if (!firing.isEmpty()) {
            executor.execute(() -> investigate(firing));
        }
        return ResponseEntity.accepted().build();
    }

    private void investigate(List<Alert> firing) {
        try {
            TriageReport report = triage.triage(firing);
            mailer.send(report);
        } catch (RuntimeException e) {
            log.error("could not triage or send for {} alert(s): {}", firing.size(), e.getClass().getSimpleName());
        }
    }

    private boolean tokenMatches(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            return false;
        }
        byte[] presented = authorization.substring(7).getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(token, presented);
    }
}
