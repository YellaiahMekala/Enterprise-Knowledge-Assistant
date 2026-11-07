package com.eka.edge.security;

import java.util.List;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jwt.Jwt;

/** The checks Spring does not provide ready-made: audience and subject. */
final class TokenValidators {

    private TokenValidators() {}

    static OAuth2TokenValidator<Jwt> audience(String expected) {
        return jwt -> {
            List<String> audiences = jwt.getAudience();
            return audiences != null && audiences.contains(expected)
                    ? OAuth2TokenValidatorResult.success()
                    : failure("the token is not meant for this service");
        };
    }

    static OAuth2TokenValidator<Jwt> subject() {
        return jwt -> {
            String subject = jwt.getSubject();
            return subject != null && !subject.isBlank()
                    ? OAuth2TokenValidatorResult.success()
                    : failure("the token has no subject");
        };
    }

    private static OAuth2TokenValidatorResult failure(String description) {
        return OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token", description, null));
    }
}
