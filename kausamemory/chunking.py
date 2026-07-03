"""Content-defined chunking for incremental sync.

Problem being solved: v1 sync re-uploads the whole encrypted snapshot every time.
As memory grows that gets expensive. Here we split the snapshot into
content-defined chunks (boundaries chosen by a rolling hash, so an edit only
shifts the chunks around it), address each chunk by BLAKE3, and a snapshot
becomes a manifest listing chunk locators. Only chunks whose content changed are
new; unchanged chunks are already stored, so a push uploads just the delta.

Each chunk is encrypted independently (same crypto as blobs), so the store still
sees only ciphertext, and each chunk is content-addressed and verifiable.

This module is pure and testable offline. Sync uses it to build a snapshot
manifest and upload only changed chunks.
"""

from __future__ import annotations

import blake3

# Content-defined chunking with Gear hashing (as used by FastCDC / restic).
# A boundary is cut when the top bits of the rolling hash are zero. The hash at a
# position depends only on the most recent bytes, never on where the previous cut
# fell, so an edit shifts only the boundaries near it. MIN/MAX bound chunk size.
MIN_CHUNK = 1024
MAX_CHUNK = 16 * 1024
_MASK = (1 << 12) - 1  # ~4 KB average chunk, aligned to SQLite page size

# Deterministic per-byte random table for the Gear rolling hash.
import random as _random
_rng = _random.Random(0xC0FFEE)
_GEAR = [_rng.getrandbits(32) for _ in range(256)]


def chunk(data: bytes) -> list[bytes]:
    """Split bytes into content-defined chunks using Gear hashing.

    The hash rolls with `h = (h << 1) + GEAR[byte]`, so it naturally forgets old
    bytes and depends only on recent input. A cut is made when the masked top bits
    are zero. Because the boundary condition at each position is purely local, an
    edit changes only the chunks around it and leaves the rest identical, which is
    what makes the sync delta small.
    """
    n = len(data)
    if n <= MIN_CHUNK:
        return [data] if data else []
    chunks: list[bytes] = []
    start = 0
    h = 0
    i = 0
    while i < n:
        h = ((h << 1) + _GEAR[data[i]]) & 0xFFFFFFFF
        size = i - start + 1
        if size >= MIN_CHUNK and ((h & _MASK) == 0 or size >= MAX_CHUNK):
            chunks.append(data[start : i + 1])
            start = i + 1
            h = 0
        i += 1
    if start < n:
        chunks.append(data[start:])
    return chunks


def chunk_id(chunk_bytes: bytes) -> str:
    return "blake3:" + blake3.blake3(chunk_bytes).hexdigest()


def build_manifest(data: bytes) -> tuple[list[str], dict[str, bytes]]:
    """Return (ordered chunk ids, {chunk_id: chunk_bytes}). The manifest is the
    ordered id list; reassembly concatenates chunks in that order."""
    order: list[str] = []
    blocks: dict[str, bytes] = {}
    for cb in chunk(data):
        cid = chunk_id(cb)
        order.append(cid)
        blocks[cid] = cb
    return order, blocks


def reassemble(order: list[str], blocks: dict[str, bytes]) -> bytes:
    return b"".join(blocks[cid] for cid in order)


def delta(order: list[str], have: set[str]) -> list[str]:
    """Which chunk ids in this manifest are not already stored (the upload set)."""
    seen: set[str] = set()
    out: list[str] = []
    for cid in order:
        if cid not in have and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out
