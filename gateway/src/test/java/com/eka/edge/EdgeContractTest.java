// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.edge;

import static org.assertj.core.api.Assertions.assertThat;

import com.eka.edge.support.EdgeFixture;
import com.eka.edge.support.EdgeTestBase;
import com.eka.edge.support.Http;
import com.eka.edge.support.StubCore;
import com.eka.edge.support.TestIdp;
import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.ECDSAVerifier;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jose.jwk.Curve;
import com.nimbusds.jose.jwk.ECKey;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.gen.ECKeyGenerator;
import com.nimbusds.jose.util.JSONObjectUtils;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.PlainJWT;
import com.nimbusds.jwt.SignedJWT;
import java.net.http.HttpResponse;
import java.text.ParseException;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

/**
 * The edge's external and internal contract, exercised over real HTTP against a real identity
 * provider key set and a stub core. Nothing here is mocked inside the edge.
 */
class EdgeContractTest extends EdgeTestBase {

    private static final Pattern PSEUDONYM = Pattern.compile("u[0-9a-f]{32}");

    private static String token(String subject) {
        return EdgeFixture.IDP.sign(TestIdp.validClaims(subject).build());
    }

    private static Map<String, Object> json(HttpResponse<String> response) {
        try {
            return JSONObjectUtils.parse(response.body());
        } catch (ParseException e) {
            throw new AssertionError("not JSON: " + response.body(), e);
        }
    }

    // --- GET /api/v1/me --------------------------------------------------------------------

    @Test
    void meWithoutATokenIsAProblemWithAChallenge() {
        HttpResponse<String> response = Http.get(EdgeFixture.edge("/api/v1/me"));

        assertThat(response.statusCode()).isEqualTo(401);
        assertThat(response.headers().firstValue("content-type")).hasValueSatisfying(
                type -> assertThat(type).startsWith("application/problem+json"));
        assertThat(response.headers().firstValue("www-authenticate")).contains("Bearer");
        Map<String, Object> body = json(response);
        assertThat(body).containsEntry("type", "urn:eka:problem:unauthorized").containsEntry("status", 401L);
        assertThat(body.get("request_id")).isNotNull();
        assertThat(response.headers().firstValue("x-request-id")).isPresent();
    }

    @Test
    void meReturnsAPseudonymNotTheProvidersSubject() {
        HttpResponse<String> response =
                Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token("alice-at-idp")));

        assertThat(response.statusCode()).isEqualTo(200);
        Map<String, Object> body = json(response);
        assertThat((String) body.get("user_id")).matches(PSEUDONYM);
        assertThat(response.body()).doesNotContain("alice-at-idp");
        assertThat(body).containsEntry("role", "user");
    }

    @Test
    void thePseudonymIsStableAndDiffersPerPerson() {
        String first = json(Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token("p1")))).get("user_id").toString();
        String again = json(Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token("p1")))).get("user_id").toString();
        String other = json(Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token("p2")))).get("user_id").toString();

        assertThat(again).isEqualTo(first);
        assertThat(other).isNotEqualTo(first);
    }

    @Test
    void anAdminRoleInTheTokenBecomesTheAdminRole() {
        String admin = EdgeFixture.IDP.sign(TestIdp.validClaims("boss").claim("roles", List.of("eka-admin")).build());
        String other = EdgeFixture.IDP.sign(TestIdp.validClaims("dev").claim("roles", List.of("something-else")).build());

        assertThat(json(Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(admin))))
                .containsEntry("role", "admin");
        assertThat(json(Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(other))))
                .containsEntry("role", "user");
    }

    @Test
    void meIsAnsweredByTheEdgeAndNeverReachesTheCore() {
        int before = EdgeFixture.CORE.count();
        Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token("alice")));
        assertThat(EdgeFixture.CORE.count()).isEqualTo(before);
    }

    // --- tokens that must be refused ----------------------------------------------------------

    static Stream<Arguments> refused() throws JOSEException {
        ECKey rogue = new ECKeyGenerator(Curve.P_256).keyID(TestIdp.KEY_ID).generate();
        Instant now = Instant.now();
        return Stream.of(
                Arguments.of("expired", EdgeFixture.IDP.sign(TestIdp.validClaims("a")
                        .issueTime(Date.from(now.minusSeconds(900)))
                        .expirationTime(Date.from(now.minusSeconds(600))).build())),
                Arguments.of("not yet valid", EdgeFixture.IDP.sign(TestIdp.validClaims("a")
                        .notBeforeTime(Date.from(now.plusSeconds(600))).build())),
                Arguments.of("wrong audience", EdgeFixture.IDP.sign(
                        TestIdp.validClaims("a").audience("another-service").build())),
                Arguments.of("wrong issuer", EdgeFixture.IDP.sign(
                        TestIdp.validClaims("a").issuer("https://evil.example").build())),
                Arguments.of("no subject", EdgeFixture.IDP.sign(TestIdp.validClaims(null).build())),
                Arguments.of("blank subject", EdgeFixture.IDP.sign(TestIdp.validClaims(" ").build())),
                Arguments.of("signed by another key with the provider's key id",
                        TestIdp.signWith(rogue, TestIdp.KEY_ID, TestIdp.validClaims("a").build())),
                Arguments.of("signed by another key with an unknown key id",
                        TestIdp.signWith(rogue, "unknown-kid", TestIdp.validClaims("a").build())),
                Arguments.of("unsigned (alg none)", new PlainJWT(TestIdp.validClaims("a").build()).serialize()),
                Arguments.of("HMAC signed with the public key as the secret", hmacConfusion()),
                Arguments.of("garbage", "not.a.jwt"),
                Arguments.of("one segment", "abc"));
    }

    private static String hmacConfusion() throws JOSEException {
        byte[] secret = EdgeFixture.IDP.publicKey().getX().decode();
        SignedJWT jwt = new SignedJWT(
                new JWSHeader.Builder(JWSAlgorithm.HS256).keyID(TestIdp.KEY_ID).build(),
                TestIdp.validClaims("a").build());
        jwt.sign(new MACSigner(secret));
        return jwt.serialize();
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("refused")
    void aBadTokenIsRefusedAndNeverReachesTheCore(String description, String token) {
        int before = EdgeFixture.CORE.count();

        for (String path : List.of("/api/v1/me", "/api/v1/documents")) {
            HttpResponse<String> response = Http.get(EdgeFixture.edge(path), "Authorization", Http.bearer(token));

            assertThat(response.statusCode()).as(description + " " + path).isEqualTo(401);
            assertThat(json(response)).containsEntry("type", "urn:eka:problem:unauthorized");
            assertThat(response.body()).doesNotContain(token);
        }
        assertThat(EdgeFixture.CORE.count()).as("the core was not called").isEqualTo(before);
    }

    @ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"Bearer ", "Basic dXNlcjpwYXNz", "Token abc", ""})
    void otherAuthorizationHeadersAreRefused(String header) {
        int before = EdgeFixture.CORE.count();
        HttpResponse<String> response = Http.get(EdgeFixture.edge("/api/v1/documents"), "Authorization", header);
        assertThat(response.statusCode()).isEqualTo(401);
        assertThat(EdgeFixture.CORE.count()).isEqualTo(before);
    }

    @Test
    void aTokenInTheQueryStringIsNotAccepted() {
        int before = EdgeFixture.CORE.count();
        HttpResponse<String> response =
                Http.get(EdgeFixture.edge("/api/v1/documents?access_token=" + token("alice")));
        assertThat(response.statusCode()).isEqualTo(401);
        assertThat(EdgeFixture.CORE.count()).isEqualTo(before);
    }

    // --- what the core receives ---------------------------------------------------------------

    @Test
    void theCoreReceivesAFreshInternalTokenAndNothingTheClientSent() throws Exception {
        String clientToken = token("alice");
        int before = EdgeFixture.CORE.count();

        HttpResponse<String> response = Http.get(
                EdgeFixture.edge("/api/v1/documents"),
                "Authorization", Http.bearer(clientToken),
                "X-API-Key", "attacker-key",
                "X-Auth-User", "root",
                "x-auth-role", "admin",
                "Cookie", "session=stolen",
                "X-Request-Id", "client-request-0001");

        assertThat(response.statusCode()).isEqualTo(200);
        assertThat(EdgeFixture.CORE.count()).isEqualTo(before + 1);
        StubCore.Received seen = EdgeFixture.CORE.received().get(before);

        assertThat(seen.hasHeader("X-API-Key")).isFalse();
        assertThat(seen.hasHeader("X-Auth-User")).isFalse();
        assertThat(seen.hasHeader("X-Auth-Role")).isFalse();
        assertThat(seen.hasHeader("Cookie")).isFalse();
        assertThat(seen.headers().values().stream().flatMap(List::stream))
                .as("the client's own token is not forwarded anywhere")
                .noneMatch(value -> value.contains(clientToken));
        assertThat(seen.header("X-Request-Id")).isEqualTo("client-request-0001");
        assertThat(response.headers().firstValue("x-request-id")).contains("client-request-0001");

        String authorization = seen.header("Authorization");
        assertThat(authorization).startsWith("Bearer ");
        SignedJWT internal = SignedJWT.parse(authorization.substring("Bearer ".length()));

        assertThat(internal.verify(new ECDSAVerifier(edgePublicKey().toECPublicKey()))).isTrue();
        assertThat(internal.getHeader().getAlgorithm()).isEqualTo(JWSAlgorithm.ES256);
        JWTClaimsSet claims = internal.getJWTClaimsSet();
        assertThat(claims.getIssuer()).isEqualTo("eka-edge");
        assertThat(claims.getAudience()).containsExactly("eka-core");
        assertThat(claims.getSubject()).matches(PSEUDONYM).isNotEqualTo("alice");
        assertThat(claims.getStringClaim("role")).isEqualTo("user");
        assertThat(claims.getStringClaim("rid")).isEqualTo("client-request-0001");
        assertThat(claims.getJWTID()).isNotBlank();
        long lifetime = claims.getExpirationTime().getTime() - claims.getIssueTime().getTime();
        assertThat(lifetime).isPositive().isLessThanOrEqualTo(60_000);
        assertThat(claims.getExpirationTime()).isAfter(new Date());
    }

    @Test
    void aMalformedRequestIdIsReplaced() {
        int before = EdgeFixture.CORE.count();
        HttpResponse<String> response = Http.get(
                EdgeFixture.edge("/api/v1/documents"),
                "Authorization", Http.bearer(token("alice")),
                "X-Request-Id", "bad id with spaces");

        String sent = EdgeFixture.CORE.received().get(before).header("X-Request-Id");
        assertThat(sent).matches("[A-Za-z0-9._-]{8,64}").isNotEqualTo("bad id with spaces");
        assertThat(response.headers().firstValue("x-request-id")).contains(sent);
    }

    @Test
    void theSameUserGetsTheSameInternalSubjectAsTheMeEndpointReports() throws Exception {
        String viaMe = json(Http.get(EdgeFixture.edge("/api/v1/me"), "Authorization", Http.bearer(token("carol"))))
                .get("user_id").toString();
        int before = EdgeFixture.CORE.count();
        Http.get(EdgeFixture.edge("/api/v1/documents"), "Authorization", Http.bearer(token("carol")));

        String authorization = EdgeFixture.CORE.received().get(before).header("Authorization");
        SignedJWT internal = SignedJWT.parse(authorization.substring("Bearer ".length()));
        assertThat(internal.getJWTClaimsSet().getSubject()).isEqualTo(viaMe);
    }

    // --- key publication and probes -----------------------------------------------------------

    @Test
    void thePublicKeySetIsServedOnTheManagementPortWithoutPrivateParts() throws Exception {
        HttpResponse<String> response = Http.get(EdgeFixture.management("/actuator/jwks"));

        assertThat(response.statusCode()).isEqualTo(200);
        JWKSet set = JWKSet.parse(response.body());
        assertThat(set.getKeys()).hasSize(1);
        assertThat(set.getKeys().get(0).isPrivate()).isFalse();
        assertThat(set.getKeys().get(0).getKeyID()).isNotBlank();
        assertThat(response.body()).doesNotContain("\"d\"");
    }

    @Test
    void theKeySetAndProbesAreNotServedOnTheApiPort() {
        assertThat(Http.get(EdgeFixture.edge("/actuator/jwks")).statusCode()).isNotEqualTo(200);
        assertThat(Http.get(EdgeFixture.edge("/actuator/health")).statusCode()).isNotEqualTo(200);
    }

    @Test
    void healthIsUpOnTheManagementPort() {
        HttpResponse<String> response = Http.get(EdgeFixture.management("/actuator/health"));
        assertThat(response.statusCode()).isEqualTo(200);
        assertThat(response.body()).contains("UP");
    }

    private static ECKey edgePublicKey() throws Exception {
        HttpResponse<String> response = Http.get(EdgeFixture.management("/actuator/jwks"));
        return (ECKey) JWKSet.parse(response.body()).getKeys().get(0);
    }
}
