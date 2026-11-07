from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Metrics:
    """One registry per app instance, so tests that build several apps do not collide."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "eka_http_requests_total",
            "HTTP requests by route template and status",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "eka_http_request_duration_seconds",
            "HTTP request duration by route template",
            ["route"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
            registry=self.registry,
        )

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests.labels(method, route, str(status)).inc()
        self.duration.labels(route).observe(seconds)

    def render(self) -> bytes:
        return generate_latest(self.registry)
