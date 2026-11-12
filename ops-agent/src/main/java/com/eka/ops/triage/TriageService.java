package com.eka.ops.triage;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import com.eka.ops.config.OpsProperties;
import com.eka.ops.tools.LogSearch;
import com.eka.ops.tools.LogStore;
import com.eka.ops.tools.LokiLogStore;
import com.eka.ops.tools.OpsTools;
import com.eka.ops.tools.ReadOnlyHttp;
import com.eka.ops.tools.RunbookReader;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.service.AiServices;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Investigates a group of alerts. With a model it runs the tool-using agent. When there is no
 * model, or the model call fails, it falls back to the runbook alone, so a report is always sent.
 */
public class TriageService {

    private static final Logger log = LoggerFactory.getLogger(TriageService.class);

    private final OpsProperties properties;
    private final ChatModel model;
    private final ReadOnlyHttp http;
    private final RunbookReader runbooks;
    private final LogStore logs;

    /** Loki when a URL is configured, else no log search. */
    public TriageService(OpsProperties properties, ChatModel model, ReadOnlyHttp http, RunbookReader runbooks) {
        this(properties, model, http, runbooks, lokiOrNull(properties, http));
    }

    /** {@code logs} may be null: the searchLogs tool then says it is not configured. */
    public TriageService(
            OpsProperties properties, ChatModel model, ReadOnlyHttp http, RunbookReader runbooks, LogStore logs) {
        this.properties = properties;
        this.model = model;
        this.http = http;
        this.runbooks = runbooks;
        this.logs = logs;
    }

    private static LogStore lokiOrNull(OpsProperties properties, ReadOnlyHttp http) {
        String url = properties.lokiUrl();
        return url == null || url.isBlank() ? null : new LokiLogStore(http, url);
    }

    public TriageReport triage(List<Alert> alerts) {
        if (model == null) {
            return fallback(alerts, 0, "No model is configured, so this report comes from the runbook only.");
        }
        OpsTools tools = new OpsTools(
                http,
                runbooks,
                properties.prometheusUrl(),
                properties.coreUrl(),
                properties.edgeManagementUrl(),
                logs == null ? null : new LogSearch(logs),
                properties.maxToolCalls());
        try {
            TriageAgent agent = AiServices.builder(TriageAgent.class)
                    .chatModel(model)
                    .tools(tools)
                    .maxSequentialToolsInvocations(properties.maxToolCalls() + 1)
                    .build();
            Triage triage = agent.investigate(describe(alerts));
            if (triage == null || triage.summary() == null || triage.summary().isBlank()) {
                return fallback(alerts, tools.callsUsed(), "The model returned no usable answer.");
            }
            return new TriageReport(alerts, triage, true, tools.callsUsed(), "");
        } catch (RuntimeException e) {
            log.warn("triage by the model failed: {}", e.getClass().getSimpleName());
            return fallback(alerts, tools.callsUsed(), "The model call failed (" + e.getClass().getSimpleName() + ").");
        }
    }

    /** A report from the runbook alone, for when the investigation itself could not run. */
    public TriageReport runbookOnly(List<Alert> alerts, String note) {
        return fallback(alerts, 0, note);
    }

    static String describe(List<Alert> alerts) {
        StringBuilder text = new StringBuilder();
        for (Alert alert : alerts) {
            text.append("- ")
                    .append(alert.name())
                    .append(" (severity ")
                    .append(alert.severity())
                    .append("): ")
                    .append(alert.summary())
                    .append('\n');
        }
        return text.toString();
    }

    private TriageReport fallback(List<Alert> alerts, int toolCalls, String note) {
        List<String> steps = new ArrayList<>();
        List<String> evidence = new ArrayList<>();
        for (Alert alert : alerts) {
            Optional<String> section = runbooks.sectionFor(alert.name());
            evidence.add(alert.name() + ": " + alert.summary());
            section.ifPresent(text -> text.lines()
                    .filter(line -> line.matches("^\\d+\\. .*"))
                    .map(line -> line.replaceFirst("^\\d+\\. ", ""))
                    .limit(5)
                    .forEach(steps::add));
        }
        if (steps.isEmpty()) {
            steps.add("Check docs/runbooks.md and the service logs.");
        }
        Triage triage = new Triage(
                alerts.size() + " alert(s) firing: " + alerts.stream().map(Alert::name).distinct().toList(),
                "Not analysed. Follow the runbook steps below.",
                evidence,
                steps);
        return new TriageReport(alerts, triage, false, toolCalls, note);
    }
}
