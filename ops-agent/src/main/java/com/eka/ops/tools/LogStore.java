package com.eka.ops.tools;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;

/**
 * Where log lines come from: Loki on the Compose stack, CloudWatch Logs on AWS. The store only
 * finds lines; the rules about what may be asked and what the model may see stay in LogSearch.
 */
public interface LogStore {

    /** One log line with its time in nanoseconds since the epoch. */
    record Line(long nanos, String text) {
        String time() {
            return Instant.ofEpochSecond(nanos / 1_000_000_000L, nanos % 1_000_000_000L)
                    .truncatedTo(ChronoUnit.SECONDS)
                    .toString();
        }
    }

    /** A store that could not answer; the message is plain text the model may read. */
    class LogStoreException extends RuntimeException {
        public LogStoreException(String message) {
            super(message);
        }
    }

    /** How the store will phrase the question, for the lines the model and the report see. */
    String describe(String service, String text);

    /**
     * At most {@code limit} lines for the service that contain the text, written in the last
     * {@code minutes}, newest first. The arguments have passed LogSearch's checks already.
     */
    List<Line> newest(String service, String text, int minutes, int limit);
}
