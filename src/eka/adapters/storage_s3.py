"""S3 file store (ADR-013). Works with AWS S3 and any S3-compatible server such as MinIO.

Same contract as the local store: keys are ``{owner_id}/{uuid}``, delete is idempotent, and a
missing or unreadable object raises ``Unavailable``. boto3 is synchronous, so each call runs in a
worker thread. Encryption at rest is the bucket's job (S3 encrypts new objects by default).
Credentials are optional: without them boto3 uses its normal chain (environment,
shared config, instance or task role), which is what a deployment on AWS should rely on.
"""

import asyncio
import re
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from eka.domain.errors import Unavailable

_KEY = re.compile(
    r"^[A-Za-z0-9_.-]{1,36}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_MISSING = {"NoSuchKey", "404", "NotFound"}


class S3FileStore:
    def __init__(
        self,
        bucket: str,
        *,
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: Any = None,
    ) -> None:
        self._bucket = bucket
        self._client = client or boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
                s3={"addressing_style": "path" if endpoint_url else "auto"},
            ),
        )

    @staticmethod
    def _check(key: str) -> str:
        if not _KEY.fullmatch(key):
            raise ValueError("invalid storage key")
        return key

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._check(key)
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as error:
            raise Unavailable("could not store the file") from error

    async def get(self, key: str) -> bytes:
        self._check(key)

        def read() -> bytes:
            body: bytes = self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
            return body

        try:
            return await asyncio.to_thread(read)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            message = "stored object is missing" if code in _MISSING else "could not read the file"
            raise Unavailable(message) from error
        except BotoCoreError as error:
            raise Unavailable("could not read the file") from error

    async def delete(self, key: str) -> None:
        self._check(key)
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as error:
            raise Unavailable("could not delete the file") from error
