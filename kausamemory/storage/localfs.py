"""LocalFS: the default, zero-config, zero-custody storage backend.

Everything stays in one directory on the user's machine. This is what makes the
out-of-the-box experience "your data never leaves your device". External,
decentralized backends (IPFS, Arweave, S3) implement the same interface and are
strictly opt-in; they are added as sibling drivers, never run by KausaLayer on
the user's behalf.
"""

from __future__ import annotations

import pathlib

from ..crypto import blob as crypto
from .base import StorageBackend


class LocalFS(StorageBackend):
    def __init__(self, root: str) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, locator: str) -> pathlib.Path:
        h = locator.split(":", 1)[1]
        return self.root / h[:2] / h[2:4] / h  # sharded to avoid huge dirs

    def put(self, ciphertext: bytes) -> str:
        locator = crypto.content_address(ciphertext)
        if not crypto.verify(locator, ciphertext):
            raise ValueError("hash mismatch on put")
        p = self._path(locator)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():  # content-addressed, so idempotent
            p.write_bytes(ciphertext)
        return locator

    def get(self, locator: str) -> bytes:
        data = self._path(locator).read_bytes()
        if not crypto.verify(locator, data):
            raise ValueError("integrity check failed: bytes do not match locator")
        return data

    def has(self, locator: str) -> bool:
        return self._path(locator).exists()

    def delete(self, locator: str) -> None:
        p = self._path(locator)
        if p.exists():
            p.unlink()
