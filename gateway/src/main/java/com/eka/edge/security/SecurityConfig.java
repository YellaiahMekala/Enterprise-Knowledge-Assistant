package com.eka.edge.security;

import com.eka.edge.error.ProblemWriter;
import java.time.Clock;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.convert.converter.Converter;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.reactive.EnableWebFluxSecurity;
import org.springframework.security.config.web.server.ServerHttpSecurity;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.security.web.server.SecurityWebFilterChain;
import org.springframework.security.web.server.context.NoOpServerSecurityContextRepository;
import reactor.core.publisher.Mono;

/**
 * Deny by default: every route needs a valid identity-provider token except the health probes.
 * Stateless (no session, no cookie), so CSRF protection has nothing to protect and is off.
 */
@Configuration
@EnableWebFluxSecurity
class SecurityConfig {

    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    @Bean
    Clock clock() {
        return Clock.systemUTC();
    }

    @Bean
    SecurityWebFilterChain securityWebFilterChain(
            ServerHttpSecurity http, ProblemWriter problems, IdentityMapper identities) {
        Converter<Jwt, Mono<AbstractAuthenticationToken>> converter = jwt -> {
            String role = identities.from(jwt).role();
            return Mono.just(new JwtAuthenticationToken(
                    jwt, List.of(new SimpleGrantedAuthority("ROLE_" + role.toUpperCase())), jwt.getSubject()));
        };
        return http.csrf(ServerHttpSecurity.CsrfSpec::disable)
                .httpBasic(ServerHttpSecurity.HttpBasicSpec::disable)
                .formLogin(ServerHttpSecurity.FormLoginSpec::disable)
                .logout(ServerHttpSecurity.LogoutSpec::disable)
                .requestCache(ServerHttpSecurity.RequestCacheSpec::disable)
                .securityContextRepository(NoOpServerSecurityContextRepository.getInstance())
                .authorizeExchange(exchange -> exchange
                        .pathMatchers("/actuator/health/**", "/actuator/health", "/actuator/info", "/actuator/jwks", "/actuator/prometheus")
                        .permitAll()
                        .anyExchange()
                        .authenticated())
                .oauth2ResourceServer(resource -> resource.jwt(jwt -> jwt.jwtAuthenticationConverter(converter))
                        .authenticationEntryPoint((exchange, error) -> {
                            // The reason stays in the log; the client only learns it was refused.
                            log.warn("request refused: {}", error.getClass().getSimpleName());
                            return problems.unauthorized(exchange);
                        })
                        .accessDeniedHandler((exchange, denied) -> problems.forbidden(exchange)))
                .exceptionHandling(Customizer.withDefaults())
                .build();
    }
}
