package com.acme.payments;

/** Retries a failed gateway call with exponential backoff. */
public final class RetryPolicy {
    public static final int MAX_ATTEMPTS = 5;
    private static final long INITIAL_DELAY_MS = 200;

    public long delayBeforeAttempt(int attempt) {
        if (attempt < 1 || attempt > MAX_ATTEMPTS) {
            throw new IllegalArgumentException("attempt out of range");
        }
        return INITIAL_DELAY_MS * (1L << (attempt - 1));
    }

    public boolean shouldRetry(int attempt, boolean idempotent) {
        return idempotent && attempt < MAX_ATTEMPTS;
    }
}
