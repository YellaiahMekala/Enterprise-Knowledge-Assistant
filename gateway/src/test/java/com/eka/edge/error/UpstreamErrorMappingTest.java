package com.eka.edge.error;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.ConnectException;
import java.nio.channels.ClosedChannelException;
import java.util.concurrent.TimeoutException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

class UpstreamErrorMappingTest {

    @Test
    void timeoutsAreGatewayTimeouts() {
        assertThat(UpstreamErrorHandler.map(new TimeoutException()).status()).isEqualTo(HttpStatus.GATEWAY_TIMEOUT);
    }

    @Test
    void aRefusedConnectionIsServiceUnavailable() {
        var wrapped = new IllegalStateException("outer", new ConnectException("refused"));
        assertThat(UpstreamErrorHandler.map(wrapped).status()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
    }

    @Test
    void aClosedConnectionIsBadGateway() {
        assertThat(UpstreamErrorHandler.map(new ClosedChannelException()).status()).isEqualTo(HttpStatus.BAD_GATEWAY);
    }

    @Test
    void gatewayStatusesFromTheRoutingLayerAreKept() {
        var error = new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT);
        assertThat(UpstreamErrorHandler.map(error).slug()).isEqualTo("gateway-timeout");
    }

    @Test
    void otherFailuresAreLeftToTheDefaultHandling() {
        assertThat(UpstreamErrorHandler.map(new IllegalArgumentException("bug"))).isNull();
        assertThat(UpstreamErrorHandler.map(new ResponseStatusException(HttpStatus.UNAUTHORIZED))).isNull();
    }
}
