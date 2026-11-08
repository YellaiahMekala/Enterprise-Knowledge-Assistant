"""Picks the file store from settings, so the API, the worker and the evaluator agree."""

from pathlib import Path

from eka.adapters.storage_local import LocalFileStore
from eka.adapters.storage_s3 import S3FileStore
from eka.config import Settings
from eka.ports.storage import FileStore


def build_file_store(settings: Settings, local_dir: Path | None = None) -> FileStore:
    if settings.storage_backend == "s3":
        assert settings.s3_bucket is not None  # checked by Settings
        return S3FileStore(
            settings.s3_bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=(
                settings.s3_secret_access_key.get_secret_value()
                if settings.s3_secret_access_key
                else None
            ),
        )
    return LocalFileStore(local_dir or settings.storage_local_dir)
