# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""S3 file store against moto (an in-process fake S3): same contract as the local store."""

import asyncio
import uuid
from collections.abc import Coroutine, Iterator
from typing import Any, TypeVar

import boto3
import pytest
from moto import mock_aws

from eka.adapters.storage import build_file_store
from eka.adapters.storage_local import LocalFileStore
from eka.adapters.storage_s3 import S3FileStore
from eka.domain.errors import Unavailable
from tests.helpers import make_settings

T = TypeVar("T")
BUCKET = "eka-test-files"


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def key(owner: str = "alice") -> str:
    return f"{owner}/{uuid.uuid4()}"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3FileStore]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield S3FileStore(BUCKET, region="us-east-1")


def test_put_get_delete_round_trip(store: S3FileStore) -> None:
    k = key()
    run(store.put(k, b"hello", "text/plain"))
    assert run(store.get(k)) == b"hello"
    run(store.delete(k))
    with pytest.raises(Unavailable, match="missing"):
        run(store.get(k))


def test_the_content_type_is_stored(store: S3FileStore) -> None:
    k = key()
    run(store.put(k, b"%PDF", "application/pdf"))
    head = boto3.client("s3", region_name="us-east-1").head_object(Bucket=BUCKET, Key=k)
    assert head["ContentType"] == "application/pdf"


def test_delete_of_a_missing_key_is_not_an_error(store: S3FileStore) -> None:
    run(store.delete(key()))


@pytest.mark.parametrize(
    "bad",
    ["", "../x", "alice/not-a-uuid", "a/b/" + str(uuid.uuid4()), "alice\\" + str(uuid.uuid4())],
)
def test_keys_must_have_the_owner_slash_uuid_shape(store: S3FileStore, bad: str) -> None:
    with pytest.raises(ValueError):
        run(store.put(bad, b"x", "text/plain"))
    with pytest.raises(ValueError):
        run(store.get(bad))
    with pytest.raises(ValueError):
        run(store.delete(bad))


def test_a_missing_bucket_is_reported_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        broken = S3FileStore("no-such-bucket", region="us-east-1")
        with pytest.raises(Unavailable):
            run(broken.put(key(), b"x", "text/plain"))
        with pytest.raises(Unavailable):
            run(broken.get(key()))


def test_the_factory_picks_the_backend_from_settings(tmp_path: Any) -> None:
    assert isinstance(build_file_store(make_settings(storage_local_dir=tmp_path)), LocalFileStore)
    s3 = build_file_store(
        make_settings(storage_backend="s3", s3_bucket=BUCKET, s3_region="us-east-1")
    )
    assert isinstance(s3, S3FileStore)


def test_s3_needs_a_bucket() -> None:
    with pytest.raises(ValueError, match="EKA_S3_BUCKET"):
        make_settings(storage_backend="s3")


def test_s3_keys_come_as_a_pair() -> None:
    with pytest.raises(ValueError, match="both"):
        make_settings(s3_access_key_id="only-one")


def test_empty_s3_values_from_an_env_file_count_as_unset() -> None:
    settings = make_settings(s3_bucket="", s3_access_key_id="", s3_secret_access_key="")
    assert settings.s3_bucket is None and settings.s3_access_key_id is None
