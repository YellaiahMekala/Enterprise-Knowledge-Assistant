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
        if (mail == null || mail.to() == null || mail.to().isBlank()) {
            log.warn("no recipient configured (EKA_ALERT_EMAIL_TO); report not sent");
            return;
        }
        SimpleMailMessage message = new SimpleMailMessage();
        message.setTo(mail.to());
        if (mail.from() != null && !mail.from().isBlank()) {
            message.setFrom(mail.from());
        }
        message.setSubject(ReportFormatter.subject(report));
        message.setText(ReportFormatter.body(report));
        sender.send(message);
        log.info("triage report sent: {}", ReportFormatter.subject(report));
    }
}
