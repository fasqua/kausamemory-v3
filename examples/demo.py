"""End-to-end demo of KausaMemory v3.

Run:  PYTHONPATH=. python3 examples/demo.py

Shows:
  1. verbatim-first storage
  2. four-channel RRF retrieval (which channels fired per hit)
  3. supersede-not-delete on a near-duplicate update
  4. the sovereignty round-trip: snapshot -> encrypt -> content-address ->
     LocalFS -> fetch -> verify -> decrypt, driven by a monotonic head pointer
  5. proof that the core path made zero cloud LLM calls
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from kausamemory import KausaMemory
from kausamemory.embed.embedder import FastEmbedEmbedder
from kausamemory.crypto import blob as crypto
from kausamemory.solana.head import LocalHead
from kausamemory.storage.localfs import LocalFS
from kausamemory.sync import Sync


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="kausamemory-demo-"))
    m = KausaMemory(path=str(workdir / "mem.db"), embedder=FastEmbedEmbedder())

    print("=" * 70)
    print("1) STORE (verbatim-first)")
    facts = [
        "Edu is the lead developer of KausaLayer, a privacy protocol on Solana.",
        "KausaMemory uses sqlite-vec for local vector search inside one file.",
        "The KAUSA token settles x402 micropayments on Solana.",
        "Maze Pocket is a stealth wallet system with golden ratio splits.",
        "The team prefers verbatim storage over LLM-extracted facts.",
    ]
    for f in facts:
        r = m.store(f)
        print(f"   [{r.action:9}] #{r.episode_id}  {f[:52]}...")

    print("\n2) SEARCH (four-channel RRF fusion)")
    for q in ["What does KausaMemory use for vector search?",
              "How are payments settled on Solana?"]:
        print(f"\n   query: {q}")
        for hit in m.search(q, limit=3):
            print(f"     score={hit.score:.4f}  [{'+'.join(hit.channels):22}]  {hit.content[:46]}...")

    print("\n3) SUPERSEDE, not delete (near-duplicate update of fact #2)")
    r = m.store("KausaMemory uses sqlite-vec for local vector search inside a single file.")
    print(f"   action={r.action}  new=#{r.episode_id}  superseded=#{r.superseded}")
    print(f"   stats: {m.stats()}")

    print("\n4) SOVEREIGNTY ROUND-TRIP (encrypt -> address -> store -> restore)")
    key = crypto.derive_key("correct horse battery staple",
                            crypto.derive_salt("So1anaPubkeyExample1111111111111111111111111"))
    backend = LocalFS(str(workdir / "blobs"))
    head = LocalHead(str(workdir / "head.json"))
    sync = Sync(backend, head)
    h1 = sync.push(m.db, key)
    print(f"   pushed snapshot: seq={h1.seq}  cid={h1.cid[:24]}...")
    m.store("A second snapshot bumps the monotonic head sequence.")
    h2 = sync.push(m.db, key)
    print(f"   pushed snapshot: seq={h2.seq}  cid={h2.cid[:24]}...")
    restored = sync.pull(key)
    print(f"   restored + integrity-verified: {len(restored):,} bytes of SQL")
    bad = bytearray(backend.get(h2.cid)); bad[-1] ^= 0x01
    print(f"   tamper detection: corrupted blob verifies == {crypto.verify(h2.cid, bytes(bad))} (expected False)")

    print("\n5) ZERO CLOUD LLM ON THE CORE PATH")
    print(f"   cloud_llm_calls = {m.stats()['cloud_llm_calls']}  (target: 0)")
    print("=" * 70)
    m.close()


if __name__ == "__main__":
    main()
