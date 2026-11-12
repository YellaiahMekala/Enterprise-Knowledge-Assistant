import asyncio

from fastapi.testclient import TestClient

from eka import __version__
from eka.api import health
from eka.main import create_app
from tests.helpers import capture_logs, make_settings


def test_live_reports_ok(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_build_version(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_probes_need_no_credentials(client: TestClient) -> None:
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_ready_is_503_when_the_database_check_fails() -> None:
    async def database_down() -> None:
        raise ConnectionError("could not connect to server at 10.0.0.5:5432")

    app = create_app(make_settings(), readiness_check=database_down)
    with capture_logs() as records, TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["type"] == "urn:eka:problem:unavailable"
    assert "10.0.0.5" not in response.text  # driver detail is logged, not returned
    warnings = [r for r in records if r.levelname == "WARNING"]
    assert len(warnings) == 1  # one line per failed probe, not a traceback
    assert warnings[0].exc_info is None
    assert "ConnectionError" in warnings[0].getMessage()
    assert "10.0.0.5" in warnings[0].getMessage()  # the detail is in the log, not the response


def test_ready_is_503_when_the_check_hangs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(health, "READINESS_TIMEOUT_S", 0.05)

    async def hangs() -> None:
        await asyncio.sleep(10)

    app = create_app(make_settings(), readiness_check=hangs)
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 503


def test_ready_is_503_when_no_database_is_configured() -> None:
    app = create_app(make_settings())  # no database_url and no injected check
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200


# --- the embedding model in readiness (FR-52) --------------------------------------------------


def _app_with(provider_outcome: str) -> TestClient:
    from eka.main import EmbedderWarmup, _readiness

    async def database_ok() -> None:
        return None

    gate = asyncio.Event()

    async def provider() -> object:
        if provider_outcome == "fails":
            raise OSError("model download failed")
        if provider_outcome == "slow":
            await gate.wait()
        return object()

    warmup = EmbedderWarmup(provider)  # type: ignore[arg-type]
    app = create_app(make_settings(), readiness_check=_readiness(database_ok, warmup))
    original = app.router.lifespan_context

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(a):  # type: ignore[no-untyped-def]
        warmup.start()
        async with original(a):
            yield
        await warmup.stop()

    app.router.lifespan_context = lifespan
    client = TestClient(app)
    client.gate = gate  # type: ignore[attr-defined]
    return client


def test_ready_waits_for_the_embedding_model_to_load() -> None:
    with _app_with("slow") as client:
        assert client.get("/health/ready").status_code == 503
        client.portal.call(client.gate.set)  # type: ignore[attr-defined]
        for _ in range(50):
            if client.get("/health/ready").status_code == 200:
                break
        assert client.get("/health/ready").status_code == 200


def test_ready_is_503_when_the_embedding_model_cannot_load() -> None:
    with _app_with("fails") as client:
        assert client.get("/health/ready").status_code == 503
