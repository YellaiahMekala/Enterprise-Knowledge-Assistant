package com.eka.ops.tools;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * The only way the agent's tools reach other services: GET requests to a base URL fixed at
 * start-up, so a model can choose a path but never a host or a method.
 */
public class ReadOnlyHttp {

    private static final int MAX_BODY_CHARS = 4_000;

    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
    private final Duration timeout;

    public ReadOnlyHttp(Duration timeout) {
        this.timeout = timeout;
    }

    /** Status and the start of the body; failures come back as text the model can read. */
    public String get(String baseUrl, String pathAndQuery) {
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + pathAndQuery))
                    .timeout(timeout)
                    .GET()
                    .build();
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
            String body = response.body();
            if (body.length() > MAX_BODY_CHARS) {
                body = body.substring(0, MAX_BODY_CHARS) + "...[truncated]";
            }
            return "HTTP " + response.statusCode() + " " + body;
        } catch (IOException e) {
            return "unreachable: " + e.getClass().getSimpleName();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return "interrupted";
        }
    }
}
