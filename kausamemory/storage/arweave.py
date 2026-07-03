"""Arweave storage backend (permanent, pay-once storage).

Best fit for users who want durable, permanent availability and accept a one-time
cost. As with every backend, blobs are already encrypted and content-addressed,
so Arweave is dumb storage trusted only for availability; integrity is verified
client-side against the BLAKE3 locator.

Addressing: Arweave returns its own transaction id on upload. This driver keeps a
map from our BLAKE3 locator to that tx id, and fetches by it. A production
deployment would persist that map (or resolve via a tag index / GraphQL); here it
is kept in memory, matching the other drivers.

Activation: provide a wallet (JWK) and a gateway URL, e.g. https://arweave.net.
Uploading costs AR. This driver isolates that behind an injectable uploader so
the logic is testable without spending tokens.
"""

from __future__ import annotations

from typing import Callable

from ..crypto import blob as crypto
from .base import StorageBackend

# An uploader takes ciphertext bytes and returns the Arweave tx id (string).
Uploader = Callable[[bytes], str]
# A fetcher takes a tx id and returns the stored bytes.
Fetcher = Callable[[str], bytes]


class ArweaveBackend(StorageBackend):
    def __init__(
        self,
        gateway_url: str = "https://arweave.net",
        uploader: Uploader | None = None,
        fetcher: Fetcher | None = None,
        session=None,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self._tx_by_locator: dict[str, str] = {}
        self._uploader = uploader
        self._fetcher = fetcher
        self._session = session

    def _http(self):
        if self._session is None:
            import requests  # lazy

            self._session = requests.Session()
        return self._session

    def put(self, ciphertext: bytes) -> str:
        locator = crypto.content_address(ciphertext)
        if not crypto.verify(locator, ciphertext):
            raise ValueError("hash mismatch on put")
        if self._uploader is None:
            raise RuntimeError(
                "ArweaveBackend needs an uploader (wallet-signed). Inject one to activate."
            )
        self._tx_by_locator[locator] = self._uploader(ciphertext)
        return locator

    def get(self, locator: str) -> bytes:
        tx = self._tx_by_locator.get(locator)
        if tx is None:
            raise KeyError(f"no Arweave tx known for locator {locator}")
        if self._fetcher is not None:
            data = self._fetcher(tx)
        else:
            resp = self._http().get(f"{self.gateway_url}/{tx}")
            resp.raise_for_status()
            data = resp.content
        if not crypto.verify(locator, data):
            raise ValueError("integrity check failed: bytes do not match locator")
        return data

    def has(self, locator: str) -> bool:
        return locator in self._tx_by_locator

    def delete(self, locator: str) -> None:
        # Arweave is permanent; we can only forget our reference, not erase data.
        self._tx_by_locator.pop(locator, None)
