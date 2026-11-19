// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge.token;

import com.eka.edge.config.EdgeProperties;
import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JOSEObjectType;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.ECDSASigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import java.time.Clock;
import java.time.Instant;
import java.util.Date;
import java.util.UUID;
import org.springframework.stereotype.Service;

/**
 * Mints the short-lived token the core accepts (ADR-022). It carries who the caller is and what
 * role they hold; it is not a session and is never given to the browser.
 */
@Service
public class InternalTokenService {

    private final SigningKeyProvider keys;
    private final EdgeProperties.InternalToken settings;
    private final Clock clock;

    public InternalTokenService(SigningKeyProvider keys, EdgeProperties properties, Clock clock) {
        this.keys = keys;
        this.settings = properties.internalToken();
        this.clock = clock;
    }

    public String mint(String userId, String role, String requestId) {
        Instant now = clock.instant();
        JWTClaimsSet claims = new JWTClaimsSet.Builder()
                .issuer(settings.issuer())
                .audience(settings.audience())
                .subject(userId)
                .claim("role", role)
                .claim("rid", requestId)
                .jwtID(UUID.randomUUID().toString()) // for audit and log correlation only
                .issueTime(Date.from(now))
                .expirationTime(Date.from(now.plus(settings.ttl())))
                .build();
        JWSHeader header = new JWSHeader.Builder(JWSAlgorithm.ES256)
                .keyID(keys.signingKey().getKeyID())
                .type(JOSEObjectType.JWT)
                .build();
        try {
            SignedJWT jwt = new SignedJWT(header, claims);
            jwt.sign(new ECDSASigner(keys.signingKey()));
            return jwt.serialize();
        } catch (JOSEException e) {
            throw new IllegalStateException("cannot sign the internal token", e);
        }
    }
}
