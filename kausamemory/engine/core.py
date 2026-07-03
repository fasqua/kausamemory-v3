"""KausaMemory v3 core engine.

Public surface is small:
    m = KausaMemory(path="mem.db")   # local, single file
    m.store("text")                   # verbatim-first write
    m.search("query")                 # four-channel RRF retrieval
    m.forget_expired()                # TTL sweep

Zero cloud LLM on this path. Intelligence comes from verbatim storage + fusion.
An LLM (local, e.g. Ollama) may be attached later as optional enrichment; the
engine never requires one.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from ..embed.embedder import Embedder, HashEmbedder
from ..stores import database as db_mod
from ..stores.vectors import VectorStore
from .entities import extract_entities
from .reconcile import Reconciler
from .retriever import RetrievalResult, Retriever


@dataclass
class StoreResult:
    episode_id: int
    action: str  # 'add' | 'update' | 'contradict'
    superseded: int | None = None


class KausaMemory:
    def __init__(
        self,
        path: str = "kausamemory.db",
        embedder: Embedder | None = None,
        reconciler: Reconciler | None = None,
        namespace: str = "default",
    ) -> None:
        self.embedder: Embedder = embedder or HashEmbedder()
        self.db: sqlite3.Connection = db_mod.connect(path)
        self.vectors = VectorStore(self.db, dim=self.embedder.dim)
        self.reconciler = reconciler or Reconciler()
        self.retriever = Retriever(self.db, self.vectors, self.embedder)
        self.namespace = namespace
        self.llm_calls = 0  # tripwire: must stay 0 on the core path

    def store(
        self,
        content: str,
        role: str | None = None,
        namespace: str | None = None,
        ttl_seconds: float | None = None,
        meta: dict | None = None,
    ) -> StoreResult:
        ns = namespace or self.namespace
        content = content.strip()
        if not content:
            raise ValueError("cannot store empty content")

        vec = self.embedder.embed_one(content)
        neighbor_id, neighbor_text, similarity = self._nearest(vec, ns)
        action = self.reconciler.classify(content, neighbor_text, similarity)

        superseded = None
        if action in ("update", "contradict") and neighbor_id is not None:
            superseded = neighbor_id

        now = db_mod.now()
        cur = self.db.execute(
            "INSERT INTO episodes(namespace, content, role, created_at, valid_from, "
            "last_access, access_count, expires_at, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (ns, content, role, now, now, now,
             (now + ttl_seconds) if ttl_seconds else None,
             json.dumps(meta) if meta else None),
        )
        episode_id = int(cur.lastrowid)
        self.vectors.add(episode_id, vec)
        self._index_entities(episode_id, content, ns)

        if superseded is not None:
            self.db.execute(
                "UPDATE episodes SET valid_to = ?, superseded_by = ? WHERE id = ?",
                (now, episode_id, superseded),
            )
            self.vectors.remove(superseded)

        self.db.commit()
        return StoreResult(episode_id=episode_id, action=action, superseded=superseded)

    def search(
        self, query: str, namespace: str | None = None, limit: int = 8
    ) -> list[RetrievalResult]:
        ns = namespace or self.namespace
        results = self.retriever.search(query, namespace=ns, limit=limit)
        self._touch([r.episode_id for r in results])
        return results

    def retrieve(self, query: str, **kw) -> list[RetrievalResult]:
        return self.search(query, **kw)

    def context(self, query: str, limit: int = 8, **kw) -> str:
        return "\n".join(f"- {r.content}" for r in self.search(query, limit=limit, **kw))

    def forget_expired(self, namespace: str | None = None) -> int:
        ns = namespace or self.namespace
        now = db_mod.now()
        rows = self.db.execute(
            "SELECT id FROM episodes WHERE namespace = ? AND valid_to IS NULL "
            "AND expires_at IS NOT NULL AND expires_at <= ?",
            (ns, now),
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        for eid in ids:
            self.db.execute("UPDATE episodes SET valid_to = ? WHERE id = ?", (now, eid))
            self.vectors.remove(eid)
        self.db.commit()
        return len(ids)

    def stats(self, namespace: str | None = None) -> dict:
        ns = namespace or self.namespace
        active = self.db.execute(
            "SELECT COUNT(*) FROM episodes WHERE namespace = ? AND valid_to IS NULL", (ns,)
        ).fetchone()[0]
        total = self.db.execute(
            "SELECT COUNT(*) FROM episodes WHERE namespace = ?", (ns,)
        ).fetchone()[0]
        return {
            "namespace": ns,
            "active": int(active),
            "total_including_superseded": int(total),
            "embedder": type(self.embedder).__name__,
            "embedding_dim": self.embedder.dim,
            "cloud_llm_calls": self.llm_calls,
        }

    def close(self) -> None:
        self.db.close()

    def _nearest(self, vec, namespace):
        hits = self.vectors.knn(vec, k=1)
        if not hits:
            return None, None, None
        eid, distance = hits[0]
        row = self.db.execute(
            "SELECT content, namespace, valid_to FROM episodes WHERE id = ?", (eid,)
        ).fetchone()
        if row is None or row["namespace"] != namespace or row["valid_to"] is not None:
            return None, None, None
        return eid, row["content"], 1.0 - float(distance)

    def _index_entities(self, episode_id: int, content: str, namespace: str) -> None:
        now = db_mod.now()
        for name in extract_entities(content):
            self.db.execute(
                "INSERT OR IGNORE INTO entities(namespace, name, created_at) VALUES (?, ?, ?)",
                (namespace, name, now),
            )
            row = self.db.execute(
                "SELECT id FROM entities WHERE namespace = ? AND name = ?", (namespace, name)
            ).fetchone()
            if row:
                self.db.execute(
                    "INSERT OR IGNORE INTO episode_entities(episode_id, entity_id) VALUES (?, ?)",
                    (episode_id, int(row[0])),
                )

    def _touch(self, ids: list[int]) -> None:
        if not ids:
            return
        now = db_mod.now()
        self.db.executemany(
            "UPDATE episodes SET last_access = ?, access_count = access_count + 1 WHERE id = ?",
            [(now, eid) for eid in ids],
        )
        self.db.commit()
