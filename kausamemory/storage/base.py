"""StorageBackend: the abstraction that makes every disk interchangeable.

This is the actual product of the sovereignty layer. Because integrity and
privacy are guaranteed by content-addressing and encryption (not by the store),
the storage layer is dumb and swappable. No backend is load-bearing; the user
picks one or several. Pinata, if used at all, is just one driver behind this
interface instead of a hard-coded dependency. A backend is trusted only to have
the bytes, never to be honest (the client re-verifies every fetch) and never to
be discreet (the bytes are already encrypted).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    @abstractmethod
    def put(self, ciphertext: bytes) -> str:
        """Store an encrypted blob. Return its locator. Must verify the hash."""

    @abstractmethod
    def get(self, locator: str) -> bytes:
        """Fetch by locator. Caller re-verifies against the locator."""

    @abstractmethod
    def has(self, locator: str) -> bool:
        ...

    @abstractmethod
    def delete(self, locator: str) -> None:
        """Remove a blob (used for GC of old snapshots)."""
