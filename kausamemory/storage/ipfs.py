"""IPFS storage backend (kubo HTTP API, or a pinning gateway such as Pinata).

Two roles kept separate elsewhere in the system: IPFS handles availability
(pinning the encrypted blob); discovery lives on Solana (the head pointer). So
this driver only needs to add and fetch bytes by their IPFS CID.

Note on addressing: this backend keeps an internal map from our BLAKE3 locator to
the IPFS CID that IPFS assigns on add. The integrity guarantee is still ours: we
verify fetched bytes against the BLAKE3 locator, independent of IPFS.

Activation: run a kubo node (ipfs daemon) and point api_url at it, e.g.
http://127.0.0.1:5001. For a hosted pinning service, pass its add/cat endpoints.
"""

from __future__ import annotations

from ..crypto import blob as crypto
from .base import StorageBackend


class IPFSBackend(StorageBackend):
    def __init__(self, api_url: str = "http://127.0.0.1:5001", session=None) -> None:
        self.api_url = api_url.rstrip("/")
        if session is None:
            import requests  # lazy: file stays valid without requests installed

            session = requests.Session()
        self._http = session
        self._cid_by_locator: dict[str, str] = {}

    def put(self, ciphertext: bytes) -> str:
        locator = crypto.content_address(ciphertext)
        if not crypto.verify(locator, ciphertext):
            raise ValueError("hash mismatch on put")
        resp = self._http.post(
            f"{self.api_url}/api/v0/add",
            files={"file": (locator.split(":", 1)[1], ciphertext)},
        )
        resp.raise_for_status()
        self._cid_by_locator[locator] = resp.json()["Hash"]
        return locator

    def get(self, locator: str) -> bytes:
        cid = self._cid_by_locator.get(locator)
        if cid is None:
            raise KeyError(f"no IPFS CID known for locator {locator}")
        resp = self._http.post(f"{self.api_url}/api/v0/cat", params={"arg": cid})
        resp.raise_for_status()
        data = resp.content
        if not crypto.verify(locator, data):
            raise ValueError("integrity check failed: bytes do not match locator")
        return data

    def has(self, locator: str) -> bool:
        return locator in self._cid_by_locator

    def delete(self, locator: str) -> None:
        cid = self._cid_by_locator.pop(locator, None)
        if cid is not None:
            try:
                self._http.post(f"{self.api_url}/api/v0/pin/rm", params={"arg": cid})
            except Exception:
                pass  # unpin is best-effort; GC on the node reclaims later
