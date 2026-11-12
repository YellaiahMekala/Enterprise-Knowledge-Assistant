"""Count-window circuit breaker for one chat model (ADR-038). Same numbers as the edge breaker:
window 20, minimum 10 calls, opens at 50% failures, open 30 s, 3 half-open probes."""

import time
from collections import deque
from collections.abc import Callable
from enum import IntEnum


class State(IntEnum):
    CLOSED = 0
    HALF_OPEN = 1
    OPEN = 2


class CircuitBreaker:
    def __init__(
        self,
        *,
        window: int = 20,
        minimum_calls: int = 10,
        failure_rate: float = 0.5,
        open_seconds: float = 30.0,
        half_open_probes: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._results: deque[bool] = deque(maxlen=window)
        self._minimum = minimum_calls
        self._rate = failure_rate
        self._open_seconds = open_seconds
        self._probes = half_open_probes
        self._clock = clock
        self._state = State.CLOSED
        self._opened_at = 0.0
        self._probe_results: list[bool] = []
        self._probes_in_flight = 0

    @property
    def state(self) -> State:
        if self._state is State.OPEN and self._clock() - self._opened_at >= self._open_seconds:
            self._state = State.HALF_OPEN
            self._probe_results = []
            self._probes_in_flight = 0
        return self._state

    def allow(self) -> bool:
        state = self.state
        if state is State.CLOSED:
            return True
        if state is State.HALF_OPEN and self._probes_in_flight < self._probes:
            self._probes_in_flight += 1
            return True
        return False

    def record(self, ok: bool) -> None:
        state = self.state
        if state is State.HALF_OPEN:
            self._probe_results.append(ok)
            if not ok:
                self._open()
            elif len(self._probe_results) >= self._probes:
                self._state = State.CLOSED
                self._results.clear()
            return
        if state is State.OPEN:
            return
        self._results.append(ok)
        if len(self._results) >= self._minimum:
            failures = self._results.count(False)
            if failures / len(self._results) >= self._rate:
                self._open()

    def release(self) -> None:
        """A permitted call ended without a verdict (cancelled); free its probe slot."""
        if self._state is State.HALF_OPEN and self._probes_in_flight > 0:
            self._probes_in_flight -= 1

    def _open(self) -> None:
        self._state = State.OPEN
        self._opened_at = self._clock()
        self._results.clear()
