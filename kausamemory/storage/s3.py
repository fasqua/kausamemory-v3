"""S3-compatible storage backend.

Works with any S3 API: AWS S3, Cloudflare R2, Backblaze B2, MinIO. Blobs are
already encrypted and content-addressed, so the bucket is dumb storage; the
provider is trusted only for availability. Credentials come from the caller
(environment or explicit kwargs), never hard-coded.

Activation: pip install boto3, then pass a bucket plus credentials (or rely on
the ambient AWS credential chain).
"""

from __future__ import annotations

from ..crypto import blob as crypto
from .base import StorageBackend


class S3Backend(StorageBackend):
    def __init__(self, bucket: str, prefix: str = "kausamemory/", client=None, **client_kwargs) -> None:
        self.bucket = bucket
        self.prefix = prefix
        if client is None:
            import boto3  # lazy: file stays valid without boto3 installed

            client = boto3.client("s3", **client_kwargs)
        self._s3 = client

    def _key(self, locator: str) -> str:
        h = locator.split(":", 1)[1]
        return f"{self.prefix}{h[:2]}/{h[2:4]}/{h}"

    def put(self, ciphertext: bytes) -> str:
        locator = crypto.content_address(ciphertext)
        if not crypto.verify(locator, ciphertext):
            raise ValueError("hash mismatch on put")
        if not self.has(locator):  # content-addressed, idempotent
            self._s3.put_object(Bucket=self.bucket, Key=self._key(locator), Body=ciphertext)
        return locator

    def get(self, locator: str) -> bytes:
        obj = self._s3.get_object(Bucket=self.bucket, Key=self._key(locator))
        data = obj["Body"].read()
        if not crypto.verify(locator, data):
            raise ValueError("integrity check failed: bytes do not match locator")
        return data

    def has(self, locator: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(locator))
            return True
        except Exception:
            return False

    def delete(self, locator: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self._key(locator))
