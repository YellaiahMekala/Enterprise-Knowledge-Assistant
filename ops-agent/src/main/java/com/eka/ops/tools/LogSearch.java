package com.eka.ops.tools;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Searches recent container logs in Loki. The model never writes LogQL: it picks a service from a
 * fixed list, a plain text to look for and a time window, and the query is built here. Results are
 * cut to a few short lines, and values that look like credentials are masked before the model or
 * the report sees them.
 */
public class LogSearch {

    static final Set<String> SERVICES =
            Set.of("api", "worker", "core-behind-edge", "edge", "db", "ops-agent", "prometheus", "alertmanager");
    static final int MAX_TEXT = 100;
    static final int MAX_MINUTES = 60;
    static final int MAX_LINES = 20;
    static final int MAX_LINE_CHARS = 300;

    // No quotes, backslashes or backticks, so the text cannot end the LogQL string it goes into.
    private static final Pattern TEXT = Pattern.compile("[A-Za-z0-9 _.:/=@#%+\\-\\[\\]()]*");
    private static final Pattern SECRET = Pattern.compile(
            "(?i)(api[_-]?key|x-api-key|authorization|password|passwd|secret|token)"
                    + "(\"?\\s*[:=]\\s*\"?)(bearer\\s+)?[^\\s\"',}]+");
    private static final JsonMapper JSON = JsonMapper.builder().build();

    private final ReadOnlyHttp http;
    private final String lokiUrl;

    public LogSearch(ReadOnlyHttp http, String lokiUrl) {
        this.http = http;
        this.lokiUrl = lokiUrl;
    }

    /** Returns null when the arguments are acceptable, otherwise the reason they are not. */
    static String problem(String service, String text, int minutes) {
        if (service == null || !SERVICES.contains(service)) {
            return "service must be one of " + SERVICES.stream().sorted().toList();
        }
        if (text != null && text.length() > MAX_TEXT) {
            return "the text is longer than " + MAX_TEXT + " characters";
        }
        if (text != null && !TEXT.matcher(text).matches()) {
            return "the text may hold only letters, digits, spaces and _.:/=@#%+-[]()";
        }
        if (minutes < 1 || minutes > MAX_MINUTES) {
            return "minutes must be between 1 and " + MAX_MINUTES;
        }
        return null;
    }

    static String logQl(String service, String text) {
        String selector = "{service=\"" + service + "\"}";
        return text == null || text.isBlank() ? selector : selector + " |= \"" + text.strip() + "\"";
    }

    static String redact(String line) {
        return SECRET.matcher(line).replaceAll("$1$2$3***");
    }

    public String search(String service, String text, int minutes) {
        String problem = problem(service, text, minutes);
        if (problem != null) {
            return "rejected: " + problem;
        }
        String query = logQl(service, text);
        ReadOnlyHttp.Reply reply = http.fetch(
                lokiUrl,
                "/loki/api/v1/query_range?query=" + URLEncoder.encode(query, StandardCharsets.UTF_8)
                        + "&since=" + minutes + "m&limit=" + MAX_LINES + "&direction=backward");
        if (!reply.ok()) {
            String body = reply.body();
            return reply.status() < 0
                    ? body
                    : "HTTP " + reply.status() + " " + body.substring(0, Math.min(300, body.length()));
        }
        List<Entry> lines;
        try {
            lines = parse(reply.body());
        } catch (RuntimeException e) {
            return "the log store returned an answer that could not be read";
        }
        if (lines.isEmpty()) {
            return "no log lines for " + query + " in the last " + minutes + " minutes";
        }
        StringBuilder out = new StringBuilder(lines.size() + " newest line(s) for " + query + ":\n");
        for (Entry entry : lines) {
            String shown = redact(entry.line().strip());
            if (shown.length() > MAX_LINE_CHARS) {
                shown = shown.substring(0, MAX_LINE_CHARS) + "...";
            }
            out.append(entry.time()).append(' ').append(shown).append('\n');
        }
        return out.toString();
    }

    private record Entry(long nanos, String line) {
        String time() {
            return Instant.ofEpochSecond(nanos / 1_000_000_000L, nanos % 1_000_000_000L)
                    .truncatedTo(ChronoUnit.SECONDS)
                    .toString();
        }
    }

    /** Lines from every stream, newest first, at most MAX_LINES. */
    private static List<Entry> parse(String body) {
        List<Entry> entries = new ArrayList<>();
        for (JsonNode stream : JSON.readTree(body).path("data").path("result")) {
            for (JsonNode value : stream.path("values")) {
                entries.add(new Entry(Long.parseLong(value.get(0).asString()), value.get(1).asString()));
            }
        }
        entries.sort(Comparator.comparingLong(Entry::nanos).reversed());
        return entries.stream().limit(MAX_LINES).toList();
    }
}
