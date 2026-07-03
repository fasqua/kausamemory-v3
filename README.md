# KausaMemory

A memory layer that AI agents plug into, so they stop starting from zero every session.

Most agents are stateless. Close the session and everything the agent learned about you, your goals, your context, is gone. KausaMemory is a drop-in layer that gives an agent memory that persists across sessions, stays encrypted on the operator's own device, and can move with them instead of living in someone else's cloud.

The core store-and-retrieve path makes zero calls to a cloud LLM. The intelligence comes from how memory is stored and searched, verbatim text, local vector search, and four-channel fusion, not from renting a model somewhere. That is what makes the privacy and portability real instead of a slogan.

This is v3, built from scratch. It is alpha: the local engine and the sovereignty layer are working and tested, the on-chain pointer is proven on Solana devnet, and the hosted paid path is still in progress. The status table below is honest about what runs today.

## How it works

Three layers, from the agent down to storage.

**Interface.** An agent connects over MCP, the common tool protocol, with three tools: store a memory, search memory, and pull a ready-to-prompt context block. Run it locally and it is free (Sovereign mode). Run it as a shared service and an x402 gate can meter access per call (Hosted mode).

**Engine.** Text is kept verbatim, never summarized away. Retrieval fuses four channels (semantic vectors via sqlite-vec, keyword search via FTS5, an entity graph, and recency) into one ranking with reciprocal rank fusion. New facts are reconciled against old ones, so an update supersedes a stale memory instead of piling up. No cloud LLM is called anywhere on this path.

**Sovereignty.** Everything is encrypted on the operator's device before it leaves, Argon2id to derive the key from a passphrase and AES-256-GCM for the data, then addressed by the BLAKE3 hash of its ciphertext so integrity is verifiable. Storage is pluggable: a local folder, S3, IPFS, or Arweave. A tiny pointer on Solana records the latest snapshot so any device can find the current memory without a central server, and an on-chain rule rejects rollbacks so the history cannot be silently rewound.

## Status

Alpha. Everything marked verified has been tested on a live machine.

| Layer | Component | State |
|-------|-----------|-------|
| Engine | Verbatim store (SQLite, FTS5, bi-temporal, lifecycle) | verified |
| | Vector channel (sqlite-vec KNN) | verified |
| | Four-channel RRF fusion (vector, keyword, graph, recency) | verified |
| | Reconcile (dedup, supersede-not-delete) | verified |
| | TTL and forgetting | verified |
| | Pluggable embedder (FastEmbed, or offline Hash) | verified |
| Sovereignty | Client-side crypto (Argon2id, AES-256-GCM) | verified |
| | Content-addressing (BLAKE3, encrypt then hash) | verified |
| | Chunked delta sync (content-defined chunking) | verified |
| | StorageBackend interface + LocalFS driver | verified |
| | Solana head pointer (write, read, on-chain anti-rollback) | verified on devnet |
| | S3, IPFS, Arweave drivers | built, needs your credentials |
| Interface | MCP stdio transport + CLI | verified |
| | HTTP transport, x402 live settlement | gate logic built, settlement pending |

## Install

```
pip install git+https://github.com/fasqua/kausamemory-v3
```

Or from a clone, as an editable install for development:

```
git clone https://github.com/fasqua/kausamemory-v3
cd kausamemory-v3
pip install -e .
```

Optional extras, pulled in only if you need them:

```
pip install -e ".[embed]"    # production embedder (FastEmbed)
pip install -e ".[mcp]"      # MCP stdio transport
pip install -e ".[solana]"   # on-chain head pointer
pip install -e ".[s3]"       # S3 / R2 / MinIO storage
```

## Use it from Python

```python
from kausamemory import KausaMemory

m = KausaMemory(path="mem.db")
m.store("The user is building a Solana app and prefers Rust for backends.")

for hit in m.search("what language does the user like?"):
    print(hit.score, hit.channels, hit.content)
```

By default this uses the offline hash embedder, which needs no download. For real semantic quality, pass the production embedder:

```python
from kausamemory.embed.embedder import FastEmbedEmbedder
m = KausaMemory(path="mem.db", embedder=FastEmbedEmbedder())
```

## Connect an agent over MCP

Installing the package gives you a command any MCP client can spawn:

```
kausamemory-mcp --db /path/to/memory.db
```

Point your MCP client at that command. It exposes three tools: `memory_store`, `memory_search`, and `memory_context`. This is Sovereign mode: local, on-device, no payment.

## Anchor memory on Solana (optional)

The head pointer records the latest snapshot on-chain so memory can move between devices, and the program rejects any attempt to roll the history back to an older version. It runs today on devnet. Program id:

```
4VfiKtC5LXu5R72gKR9UwtRcFJ21uQsSMDSyTiAWdjR4
```

## Project layout

```
kausamemory/
  engine/      core.py, retriever.py (RRF), reconcile.py, entities.py
  stores/      database.py (schema), vectors.py (sqlite-vec)
  embed/       embedder.py (FastEmbed, Hash)
  crypto/      blob.py (Argon2id, AES-256-GCM, BLAKE3)
  storage/     base.py, localfs.py, s3.py, ipfs.py, arweave.py
  solana/      head.py (LocalHead, SolanaHead)
  chunking.py  content-defined chunking (Gear hashing)
  sync.py      snapshot, chunk, encrypt, push, restore
  interfaces/  mcp_server.py (tools + stdio), x402.py (payment gate)
  mcp.py       kausamemory-mcp entry point
solana-program/  Anchor program for the head pointer
examples/        demo.py
tests/           eval_recall.py
```

## Roadmap

- Engine and local sovereignty: done and verified.
- Chunked delta sync: done and verified.
- Solana head pointer: done and verified on devnet, mainnet next.
- External storage drivers (S3, IPFS, Arweave): built, waiting on real credentials.
- MCP stdio transport: done and verified.
- HTTP transport and live x402 settlement: in progress.
- KausaWorld integration: a per-player mentor keyed to a Solana wallet, ask-and-listen rather than reading a profile database.

## Links

- X: https://x.com/kausalayer
- Web: https://kausalayer.com
- Telegram: https://t.me/kausalayerportal

## License

MIT
