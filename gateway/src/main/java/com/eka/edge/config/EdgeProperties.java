package com.eka.edge.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.net.URI;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;
import org.springframework.validation.annotation.Validated;

/**
 * Typed, validated settings. The edge refuses to start with a half-configuration: a missing
 * identity provider, pseudonym secret or signing key is an error, not a default.
 */
@Validated
@ConfigurationProperties("eka.edge")
public record EdgeProperties(
        @NotNull URI coreUrl,
        @Valid @NotNull Oidc oidc,
        @Valid @NotNull InternalToken internalToken,
        @NotBlank @Size(min = 16) String pseudonymSecret,
        @DefaultValue("roles") String rolesClaim,
        @DefaultValue("eka-admin") String adminRole,
        @Valid @DefaultValue RateLimit rateLimit) {

    /** Requests a single user may make: a burst, then a steady rate. */
    public record RateLimit(
            @DefaultValue("20") @Positive int burst,
            @DefaultValue("5") @Positive double perSecond) {}

    /** The identity provider whose tokens the edge accepts. */
    public record Oidc(
            @NotBlank String issuer,
            @NotBlank String jwkSetUri,
            @NotBlank String audience,
            @NotEmpty @DefaultValue({"RS256", "ES256"}) List<String> algorithms,
            @DefaultValue("5s") Duration clockSkew) {}

    /** The short-lived token the edge issues to the core. */
    public record InternalToken(
            @DefaultValue("eka-edge") String issuer,
            @DefaultValue("eka-core") String audience,
            @DefaultValue("60s") Duration ttl,
            Path signingKeyFile,
            @DefaultValue("false") boolean ephemeralKey) {

        public InternalToken {
            // An unset environment variable arrives as an empty string: treat it as "not set".
            if (signingKeyFile != null && signingKeyFile.toString().isBlank()) {
                signingKeyFile = null;
            }
        }

        @AssertTrue(message = "ttl must be positive and at most 60 seconds")
        public boolean isTtlWithinLimit() {
            return ttl != null
                    && !ttl.isNegative()
                    && !ttl.isZero()
                    && ttl.compareTo(Duration.ofSeconds(60)) <= 0;
        }

        @AssertTrue(message = "set signing-key-file, or ephemeral-key=true for local development")
        public boolean isSigningKeyConfigured() {
            return signingKeyFile != null || ephemeralKey;
        }
    }
}
