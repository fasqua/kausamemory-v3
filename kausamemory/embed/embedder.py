"""Pluggable embedders.

Design rule: the engine depends on the `Embedder` protocol, never on a concrete
model. Production uses `FastEmbedEmbedder` (local, on-device, zero cloud). The
`HashEmbedder` is a deterministic, dependency-free fallback for offline
development and tests. Both run entirely on the user's machine: memory content
never leaves the device to be embedded.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_one(self, text: str) -> list[float]:
        ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _tokenize(text: str) -> list[str]:
    out, cur = [], []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


class HashEmbedder:
    """Deterministic hashing embedder. Not semantically strong; its only jobs are
    (1) to let the full pipeline run and be tested with zero downloads, and
    (2) to give stable vectors so tests are reproducible. Uses the hashing trick
    then L2-normalizes."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _tokenize(text):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            idx = h % self.dim
            sign = 1.0 if (h >> 1) & 1 else -1.0
            v[idx] += sign
        return _l2_normalize(v)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self._vec(text)


class FastEmbedEmbedder:
    """Production embedder. Runs a small local model via fastembed (ONNX, CPU).
    The model downloads once on first use, then runs offline. Default in real
    deployments."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name)
        probe = next(iter(self._model.embed(["_probe_"])))
        self.dim = len(probe)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [_l2_normalize(list(map(float, v))) for v in self._model.embed(list(texts))]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
