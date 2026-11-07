package com.eka.edge.security;

import com.eka.edge.config.EdgeProperties;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.Collection;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.stereotype.Component;

/**
 * Turns a verified identity-provider token into the identity the core sees.
 *
 * <p>The core never receives the provider's subject. It receives a pseudonym: an HMAC of issuer
 * and subject under a secret only the edge holds, shaped like the core's user-id pattern
 * ({@code ^[A-Za-z0-9_.-]{1,36}$}). The same person always maps to the same id, and nobody
 * without the secret can map an id back or build one for a chosen subject.
 */
@Component
public class IdentityMapper {

    private static final String HMAC = "HmacSHA256";
    private static final int ID_HEX_LENGTH = 32;

    private final byte[] secret;
    private final String rolesClaim;
    private final String adminRole;

    public IdentityMapper(EdgeProperties properties) {
        this.secret = properties.pseudonymSecret().getBytes(StandardCharsets.UTF_8);
        this.rolesClaim = properties.rolesClaim();
        this.adminRole = properties.adminRole();
    }

    public Identity from(Jwt jwt) {
        return new Identity(pseudonym(jwt.getClaimAsString("iss"), jwt.getSubject()), roleOf(jwt));
    }

    String pseudonym(String issuer, String subject) {
        try {
            Mac mac = Mac.getInstance(HMAC);
            mac.init(new SecretKeySpec(secret, HMAC));
            byte[] digest = mac.doFinal((issuer + "\n" + subject).getBytes(StandardCharsets.UTF_8));
            return "u" + HexFormat.of().formatHex(digest).substring(0, ID_HEX_LENGTH);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("HMAC-SHA256 is not available", e);
        }
    }

    private String roleOf(Jwt jwt) {
        return roleNames(jwt).contains(adminRole) ? Identity.ADMIN : Identity.USER;
    }

    /** Roles from the configured claim, or from a Keycloak-style {@code realm_access.roles}. */
    private Collection<String> roleNames(Jwt jwt) {
        Object direct = jwt.getClaim(rolesClaim);
        if (direct instanceof String single) {
            return List.of(single);
        }
        if (direct instanceof Collection<?> many) {
            return many.stream().map(String::valueOf).toList();
        }
        Object realm = jwt.getClaim("realm_access");
        if (realm instanceof Map<?, ?> map && map.get("roles") instanceof Collection<?> roles) {
            return roles.stream().map(String::valueOf).toList();
        }
        return List.of();
    }
}
