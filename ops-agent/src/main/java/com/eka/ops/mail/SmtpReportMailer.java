package com.eka.ops.mail;

import com.eka.ops.config.OpsProperties;
import com.eka.ops.triage.TriageReport;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;

public class SmtpReportMailer implements ReportMailer {

    private static final Logger log = LoggerFactory.getLogger(SmtpReportMailer.class);

    private final JavaMailSender sender;
    private final OpsProperties.Mail mail;

    public SmtpReportMailer(JavaMailSender sender, OpsProperties.Mail mail) {
        this.sender = sender;
        this.mail = mail;
    }

    @Override
    public void send(TriageReport report) {
        deliver(ReportFormatter.subject(report), ReportFormatter.body(report));
        log.info("triage report sent: {}", ReportFormatter.subject(report));
    }

    @Override
    public void sendNotice(String subject, String body) {
        deliver(subject, body);
        log.info("triage failure notice sent: {}", subject);
    }

    /** A missing recipient throws, so the batch counts as failed instead of looking sent. */
    private void deliver(String subject, String body) {
        if (mail == null || mail.to() == null || mail.to().isBlank()) {
            throw new IllegalStateException("no recipient configured (EKA_ALERT_EMAIL_TO); nothing was sent");
        }
        SimpleMailMessage message = new SimpleMailMessage();
        message.setTo(mail.to());
        if (mail.from() != null && !mail.from().isBlank()) {
            message.setFrom(mail.from());
        }
        message.setSubject(subject);
        message.setText(body);
        sender.send(message);
    }
}
