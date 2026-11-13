package com.eka.ops.tools;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Loki over its HTTP query API, one GET per search, LogQL built here from checked parts. */
public class LokiLogStore implements LogStore {

    private static final JsonMapper JSON = JsonMapper.builder().build();

    private final ReadOnlyHttp http;
    private final String lokiUrl;

    public LokiLogStore(ReadOnlyHttp http, String lokiUrl) {
        this.http = http;
        this.lokiUrl = lokiUrl;
    }

    @Override
    public String describe(String service, String text) {
        String selector = "{service=\"" + service + "\"}";
        if (text == null || text.isBlank()) {
            return selector;
        }
        if (LogLevels.isLevelSearch(text)) {
            return selector + " |~ \"" + String.join("|", LogLevels.PROBLEM_TERMS) + "\"";
        }
        return selector + " |= \"" + text.strip() + "\"";
    }

    @Override
    public List<Line> newest(String service, String text, int minutes, int limit) {
        ReadOnlyHttp.Reply reply = http.fetch(
                lokiUrl,
                "/loki/api/v1/query_range?query=" + URLEncoder.encode(describe(service, text), StandardCharsets.UTF_8)
                        + "&since=" + minutes + "m&limit=" + limit + "&direction=backward");
        if (!reply.ok()) {
            String body = reply.body();
            throw new LogStoreException(reply.status() < 0
                    ? body
                    : "HTTP " + reply.status() + " " + body.substring(0, Math.min(300, body.length())));
        }
        List<Line> lines = new ArrayList<>();
        try {
            for (JsonNode stream : JSON.readTree(reply.body()).path("data").path("result")) {
                for (JsonNode value : stream.path("values")) {
                    lines.add(new Line(Long.parseLong(value.get(0).asString()), value.get(1).asString()));
                }
            }
        } catch (RuntimeException e) {
            throw new LogStoreException("the log store returned an answer that could not be read");
        }
        lines.sort(Comparator.comparingLong(Line::nanos).reversed());
        return lines.stream().limit(limit).toList();
    }
}
