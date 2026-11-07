package com.eka.edge.token;

import com.eka.edge.config.EdgeProperties;
import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.jwk.Curve;
import com.nimbusds.jose.jwk.ECKey;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.gen.ECKeyGenerator;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.ParseException;
import org.springframework.stereotype.Component;

/**
 * Holds the key the edge signs internal tokens with. This is the only class that touches the
 * private key (an architecture test enforces that); everything else sees the public key set.
 *
 * <p>The key file is a private EC P-256 JWK ({@code python -m eka.tools.gen_edge_key} writes
 * one). An ephemeral key, for local development only, is generated at start-up.
 */
@Component
public class SigningKeyProvider {

    private final ECKey key;

    public SigningKeyProvider(EdgeProperties properties) {
        this.key = load(properties.internalToken());
    }

    private static ECKey load(EdgeProperties.InternalToken settings) {
        try {
            if (settings.signingKeyFile() != null) {
                String json = Files.readString(settings.signingKeyFile(), StandardCharsets.UTF_8);
                ECKey loaded = ECKey.parse(json);
                if (!loaded.isPrivate() || !Curve.P_256.equals(loaded.getCurve())) {
                    throw new IllegalStateException("the signing key must be a private P-256 JWK");
                }
                return loaded.getKeyID() != null
                        ? loaded
                        : new ECKey.Builder(loaded).keyIDFromThumbprint().build();
            }
            return new ECKeyGenerator(Curve.P_256).keyIDFromThumbprint(true).generate();
        } catch (IOException | ParseException | JOSEException e) {
            throw new IllegalStateException("cannot load the internal-token signing key", e);
        }
    }

    ECKey signingKey() {
        return key;
    }

    /** The public half only, in the form the core fetches. */
    public JWKSet publicKeys() {
        return new JWKSet(key.toPublicJWK());
    }
}
