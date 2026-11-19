// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.support;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * A stand-in for the RAG core. It records every request it receives, answers JSON, and streams
 * server-sent events slowly so tests can tell streaming from buffering and can see when the
 * client went away.
 */
public final class StubCore implements AutoCloseable {

    public record Received(String method, String path, Map<String, List<String>> headers) {

        public String header(String name) {
            return headers.entrySet().stream()
                    .filter(entry -> entry.getKey().equalsIgnoreCase(name))
                    .map(entry -> entry.getValue().isEmpty() ? null : entry.getValue().get(0))
                    .findFirst()
                    .orElse(null);
        }

        public boolean hasHeader(String name) {
            return headers.keySet().stream().anyMatch(key -> key.equalsIgnoreCase(name));
        }
    }

    public static final int STREAM_EVENTS = 6;
    public static final long STREAM_INTERVAL_MS = 500;
    private static final long HANG_MS = 6_000;

    private final HttpServer server;
    // The default executor runs one request at a time, so a hung request would stall every later one.
    private final ExecutorService workers = Executors.newCachedThreadPool();
    private final List<Received> received = Collections.synchronizedList(new ArrayList<>());
    private final AtomicLong streamStartedAt = new AtomicLong();
    private final AtomicLong streamCompletedAt = new AtomicLong();
    private final AtomicLong clientGoneAt = new AtomicLong();
    private final AtomicReference<String> lastStreamRequestId = new AtomicReference<>();

    public StubCore() {
        try {
            this.server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        } catch (IOException e) {
            throw new IllegalStateException(e);
        }
        server.setExecutor(workers);
        server.createContext("/", this::handle);
        server.start();
    }

    public String url() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    public List<Received> received() {
        synchronized (received) {
            return List.copyOf(received);
        }
    }

    public int count() {
        return received.size();
    }

    /** Waits until no stream is in progress (the last one completed or lost its client). */
    public void awaitIdle() throws InterruptedException {
        long deadline = System.currentTimeMillis() + 10_000;
        while (streamStartedAt.get() != 0
                && streamCompletedAt.get() == 0
                && clientGoneAt.get() == 0
                && System.currentTimeMillis() < deadline) {
            Thread.sleep(25);
        }
    }

    public void resetStream() {
        streamStartedAt.set(0);
        streamCompletedAt.set(0);
        clientGoneAt.set(0);
    }

    public long streamStartedAt() {
        return streamStartedAt.get();
    }

    public long streamCompletedAt() {
        return streamCompletedAt.get();
    }

    public long clientGoneAt() {
        return clientGoneAt.get();
    }

    public String lastStreamRequestId() {
        return lastStreamRequestId.get();
    }

    private void handle(HttpExchange exchange) throws IOException {
        Map<String, List<String>> headers = new LinkedHashMap<>(exchange.getRequestHeaders());
        received.add(new Received(exchange.getRequestMethod(), exchange.getRequestURI().getPath(), headers));
        String path = exchange.getRequestURI().getPath();
        if (path.equals("/api/v1/stream")) {
            stream(exchange);
            return;
        }
        if (path.equals("/api/v1/drill/hang")) {
            sleepQuietly(HANG_MS);
            exchange.close();
            return;
        }
        if (path.equals("/api/v1/drill/drop")) {
            exchange.getRequestBody().readAllBytes();
            exchange.close(); // no response at all: the connection ends mid-request
            return;
        }
        byte[] body = "{\"stub\":\"core\"}".getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }

    private void stream(HttpExchange exchange) throws IOException {
        lastStreamRequestId.set(exchange.getRequestHeaders().getFirst("X-Request-Id"));
        streamStartedAt.set(System.currentTimeMillis());
        exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
        exchange.getResponseHeaders().add("Cache-Control", "no-cache");
        exchange.sendResponseHeaders(200, 0); // chunked
        try (OutputStream out = exchange.getResponseBody()) {
            for (int i = 1; i <= STREAM_EVENTS; i++) {
                out.write(("event: token\ndata: {\"n\":" + i + "}\n\n").getBytes(StandardCharsets.UTF_8));
                out.flush();
                Thread.sleep(STREAM_INTERVAL_MS);
            }
            streamCompletedAt.set(System.currentTimeMillis());
        } catch (IOException e) {
            clientGoneAt.set(System.currentTimeMillis());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public void close() {
        server.stop(0);
        workers.shutdownNow();
    }
}
