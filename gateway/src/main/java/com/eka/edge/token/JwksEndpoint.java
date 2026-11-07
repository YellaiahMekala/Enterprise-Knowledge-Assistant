package com.eka.edge.token;

import java.util.Map;
import org.springframework.boot.actuate.endpoint.annotation.Endpoint;
import org.springframework.boot.actuate.endpoint.annotation.ReadOperation;
import org.springframework.stereotype.Component;

/**
 * The public keys the core uses to verify internal tokens, at {@code /actuator/jwks}.
 *
 * <p>It is served on the management port, which the Compose stack does not publish, so the key
 * set is reachable from the private network only.
 */
@Component
@Endpoint(id = "jwks")
public class JwksEndpoint {

    private final SigningKeyProvider keys;

    public JwksEndpoint(SigningKeyProvider keys) {
        this.keys = keys;
    }

    @ReadOperation
    public Map<String, Object> jwks() {
        return keys.publicKeys().toJSONObject(true);
    }
}
