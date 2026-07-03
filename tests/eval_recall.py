"""Known-answer retrieval check with the production embedder (FastEmbed).

Stores a set of facts, runs queries whose correct target we know, and reports how
often the right fact ranks #1 and appears in the top-3. This is the real signal
for "smart without a cloud LLM": retrieval quality using a real embedding model.
"""

from __future__ import annotations

import os
import tempfile

from kausamemory.engine.core import KausaMemory
from kausamemory.embed.embedder import FastEmbedEmbedder

FACTS = [
    "Edu is the lead developer of KausaLayer, a privacy protocol on Solana.",
    "KausaMemory uses sqlite-vec for local vector search inside a single file.",
    "The KAUSA token settles x402 micropayments on Solana.",
    "Maze Pocket is a stealth wallet system using golden ratio splits and Fibonacci timing.",
    "KausaShield sends shielded SOL through Arcium MPC on Solana mainnet.",
    "The team prefers storing text verbatim over LLM-extracted facts.",
    "Staking uses Streamflow dynamic pools with 7, 30, and 90 day tiers.",
    "The relay backend sdp-mazepocket is written in Rust with the Axum framework.",
    "KausaWorld is a browser MMO built with Three.js on Solana.",
    "Retrieval fuses vector, keyword, graph, and temporal channels with RRF.",
]

# (query, index of the correct fact in FACTS)
QUERIES = [
    ("Who is the lead developer of KausaLayer?", 0),
    ("What does KausaMemory use for vector search?", 1),
    ("How are micropayments paid on Solana?", 2),
    ("What is the stealth wallet system called?", 3),
    ("How does KausaShield send SOL privately?", 4),
    ("Does the team extract facts with an LLM or keep raw text?", 5),
    ("What are the staking pool durations?", 6),
    ("What language and framework is the relay backend built with?", 7),
    ("What game engine powers KausaWorld?", 8),
    ("How does retrieval combine its channels?", 9),
]


def main() -> None:
    path = os.path.join(tempfile.mkdtemp(prefix="km-eval-"), "eval.db")
    m = KausaMemory(path=path, embedder=FastEmbedEmbedder())
    for f in FACTS:
        m.store(f)

    top1 = top3 = 0
    print("-" * 78)
    for q, want in QUERIES:
        hits = m.search(q, limit=3)
        got_ids = [h.episode_id for h in hits]
        want_id = want + 1  # episode ids are 1-based in insert order
        r1 = got_ids[0] == want_id if got_ids else False
        r3 = want_id in got_ids
        top1 += r1
        top3 += r3
        mark = "OK " if r1 else ("~3 " if r3 else "MISS")
        print(f"[{mark}] {q}")
        if not r1 and hits:
            print(f"       ranked #1 instead: {hits[0].content[:60]}")
    n = len(QUERIES)
    print("-" * 78)
    print(f"top-1 accuracy: {top1}/{n} = {100*top1//n}%")
    print(f"top-3 accuracy: {top3}/{n} = {100*top3//n}%")
    print(f"cloud LLM calls: {m.stats()['cloud_llm_calls']}")
    m.close()


if __name__ == "__main__":
    main()
