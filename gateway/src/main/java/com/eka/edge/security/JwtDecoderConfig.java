// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.security;

import com.eka.edge.config.EdgeProperties;
import java.util.List;
import java.util.Locale;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusReactiveJwtDecoder;
import org.springframework.security.oauth2.jwt.ReactiveJwtDecoder;

/**
 * Validates the identity provider's token: signature against its published keys, an algorithm
 * allow-list (never {@code none}, never HMAC), issuer, audience, expiry and a subject.
 */
@Configuration
class JwtDecoderConfig {

    @Bean
    ReactiveJwtDecoder jwtDecoder(EdgeProperties properties) {
        EdgeProperties.Oidc oidc = properties.oidc();
        List<SignatureAlgorithm> allowed =
                oidc.algorithms().stream().map(JwtDecoderConfig::algorithm).toList();

        NimbusReactiveJwtDecoder decoder = NimbusReactiveJwtDecoder.withJwkSetUri(oidc.jwkSetUri())
                .jwsAlgorithms(set -> {
                    set.clear();
                    set.addAll(allowed);
                })
                .build();
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                new JwtTimestampValidator(oidc.clockSkew()),
                new JwtIssuerValidator(oidc.issuer()),
                TokenValidators.audience(oidc.audience()),
                TokenValidators.subject()));
        return decoder;
    }

    private static SignatureAlgorithm algorithm(String name) {
        String upper = name.toUpperCase(Locale.ROOT);
        SignatureAlgorithm algorithm = SignatureAlgorithm.from(upper);
        if (algorithm == null || upper.startsWith("HS")) {
            // HMAC algorithms are refused: with a public key set they invite algorithm confusion.
            throw new IllegalStateException("unsupported or unsafe signature algorithm: " + name);
        }
        return algorithm;
    }
}
