# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""S3 file store against a real S3-compatible server (Adobe S3Mock in a container), over HTTP.

The moto tests cover the adapter's logic in-process; this one proves it talks to a server through
a real endpoint URL with path-style addressing, as it would with MinIO or any other S3 clone."""

import asyncio
import secrets
import uuid
from collections.abc import Iterator

import pytest

from eka.adapters.storage_s3 import S3FileStore
from eka.domain.errors import Unavailable

IMAGE = "adobe/s3mock:4.7.0"
BUCKET = "eka-files"


@pytest.fixture(scope="module")
def store() -> Iterator[S3FileStore]:
    try:
        import docker

        docker.from_env().ping()
    except Exception as error:
        pytest.skip(f"Docker is not available: {type(error).__name__}")

    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy

    container = (
        DockerContainer(IMAGE)
        .with_env("COM_ADOBE_TESTING_S3MOCK_STORE_INITIAL_BUCKETS", BUCKET)
        .with_exposed_ports(9090)
        .waiting_for(LogMessageWaitStrategy("Started S3MockApplication"))
    )
    with container:
        endpoint = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9090)}"
        yield S3FileStore(
            BUCKET,
            region="us-east-1",
            endpoint_url=endpoint,
            access_key_id="test-key",
            secret_access_key="test-secret",
        )


def test_round_trip_over_the_network(store: S3FileStore) -> None:
    key = f"alice/{uuid.uuid4()}"
    payload = b"%PDF-1.7 " + secrets.token_bytes(64 * 1024)
    asyncio.run(store.put(key, payload, "application/pdf"))
    assert asyncio.run(store.get(key)) == payload
    asyncio.run(store.delete(key))
    asyncio.run(store.delete(key))  # idempotent
    with pytest.raises(Unavailable, match="missing"):
        asyncio.run(store.get(key))


def test_a_missing_bucket_is_reported_as_unavailable(store: S3FileStore) -> None:
    other = S3FileStore(
        "no-such-bucket",
        region="us-east-1",
        endpoint_url=store._client.meta.endpoint_url,
        access_key_id="test-key",
        secret_access_key="test-secret",
    )
    with pytest.raises(Unavailable):
        asyncio.run(other.put(f"alice/{uuid.uuid4()}", b"x", "text/plain"))
