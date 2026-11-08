package com.eka.ops.config;

import com.eka.ops.mail.ReportMailer;
import com.eka.ops.mail.SmtpReportMailer;
import com.eka.ops.tools.ReadOnlyHttp;
import com.eka.ops.tools.RunbookReader;
import com.eka.ops.triage.TriageService;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.openai.OpenAiChatModel;
import java.time.Duration;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.mail.javamail.JavaMailSender;

@Configuration
public class AgentConfig {

    /** Null when no api key is set: the service then reports from the runbook alone. */
    @Bean
    ChatModel chatModel(OpsProperties properties) {
        OpsProperties.Model model = properties.model();
        if (model == null || model.apiKey() == null || model.apiKey().isBlank()) {
            return null;
        }
        OpenAiChatModel.OpenAiChatModelBuilder builder = OpenAiChatModel.builder()
                .apiKey(model.apiKey())
                .modelName(model.name())
                .temperature(0.0)
                .timeout(Duration.ofSeconds(60))
                .maxRetries(1);
        if (model.baseUrl() != null && !model.baseUrl().isBlank()) {
            builder.baseUrl(model.baseUrl());
        }
        return builder.build();
    }

    @Bean
    TriageService triageService(OpsProperties properties, ObjectProvider<ChatModel> model) {
        return new TriageService(
                properties,
                model.getIfAvailable(),
                new ReadOnlyHttp(properties.toolTimeout()),
                new RunbookReader(properties.runbookFile()));
    }

    @Bean
    ReportMailer reportMailer(JavaMailSender sender, OpsProperties properties) {
        return new SmtpReportMailer(sender, properties.mail());
    }

    @Bean
    Executor triageExecutor() {
        return Executors.newVirtualThreadPerTaskExecutor();
    }
}
