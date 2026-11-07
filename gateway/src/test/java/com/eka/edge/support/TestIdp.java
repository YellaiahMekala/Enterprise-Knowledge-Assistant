package com.eka.edge.support;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.ECDSASigner;
import com.nimbusds.jose.jwk.Curve;
import com.nimbusds.jose.jwk.ECKey;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.gen.ECKeyGenerator;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;

/**
 * A stand-in identity provider: a real HTTP server publishing a real key set, and a way to sign
 * tokens with the matching private key. The edge talks to it exactly as it would to a provider.
 */
public final class TestIdp implements AutoCloseable {

    public static final String ISSUER = "https://idp.test/realms/eka";
    public static final String AUDIENCE = "eka-api";
    public static final String KEY_ID = "idp-key-1";

    private final ECKey key;
    private final HttpServer server;

    public TestIdp() {
        try {
            this.key = new ECKeyGenerator(Curve.P_256).keyID(KEY_ID).generate();
            this.server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        } catch (JOSEException | IOException e) {
            throw new IllegalStateException(e);
        }
        server.createContext("/jwks", exchange -> {
            byte[] body = new JWKSet(key.toPublicJWK()).toString().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
    }

    public String jwkSetUri() {
        return "http://127.0.0.1:" + server.getAddress().getPort() + "/jwks";
    }

    public ECKey publicKey() {
        return key.toPublicJWK();
    }

    /** A claim set that every check accepts; tests change one thing at a time. */
    public static JWTClaimsSet.Builder validClaims(String subject) {
        Instant now = Instant.now();
        return new JWTClaimsSet.Builder()
                .issuer(ISSUER)
                .audience(AUDIENCE)
                .subject(subject)
                .issueTime(Date.from(now))
                .expirationTime(Date.from(now.plusSeconds(300)));
    }

    public String sign(JWTClaimsSet claims) {
        return signWith(key, KEY_ID, claims);
    }

    /** Signs with any key, optionally claiming the provider's key id (a forgery attempt). */
    public static String signWith(ECKey signer, String keyId, JWTClaimsSet claims) {
        try {
            SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.ES256).keyID(keyId).build(), claims);
            jwt.sign(new ECDSASigner(signer));
            return jwt.serialize();
        } catch (JOSEException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
