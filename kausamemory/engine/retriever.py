"""Retrieval = four channels fused with Reciprocal Rank Fusion (RRF).

Channels (all local, zero LLM):
  1. vector    - semantic similarity via sqlite-vec KNN
  2. keyword   - lexical via FTS5
  3. graph     - episodes sharing entities with the query
  4. temporal  - recency

Each channel returns an ordered list of episode ids. RRF combines them with pure
arithmetic: an item scores sum(weight / (k + rank)) across the lists it appears
in. Items that rank well in several channels rise to the top. No model, no
training, no cloud call.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..embed.embedder import Embedder
from ..stores.vectors import VectorStore
from .entities import extract_entities


@dataclass
class RetrievalResult:
    episode_id: int
    content: str
    score: float
    channels: list[str] = field(default_factory=list)


DEFAULT_WEIGHTS = {"vector": 1.0, "keyword": 1.0, "graph": 0.7, "temporal": 0.5}


class Retriever:
    def __init__(
        self,
        db: sqlite3.Connection,
        vectors: VectorStore,
        embedder: Embedder,
        weights: dict[str, float] | None = None,
        rrf_k: int = 60,
    ) -> None:
        self.db = db
        self.vectors = vectors
        self.embedder = embedder
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.rrf_k = rrf_k

    def _vector(self, query: str, namespace: str, pool: int) -> list[int]:
        hits = self.vectors.knn(self.embedder.embed_one(query), k=pool)
        return self._filter_ns_valid([eid for eid, _ in hits], namespace)

    def _keyword(self, query: str, namespace: str, pool: int) -> list[int]:
        match = _fts_query(query)
        if not match:
            return []
        try:
            rows = self.db.execute(
                "SELECT e.id FROM episodes_fts f JOIN episodes e ON e.id = f.rowid "
                "WHERE episodes_fts MATCH ? AND e.namespace = ? AND e.valid_to IS NULL "
                "ORDER BY rank LIMIT ?",
                (match, namespace, pool),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [int(r[0]) for r in rows]

    def _graph(self, query: str, namespace: str, pool: int) -> list[int]:
        names = extract_entities(query)
        if not names:
            return []
        placeholders = ",".join("?" * len(names))
        rows = self.db.execute(
            f"SELECT ee.episode_id, COUNT(*) AS shared "
            f"FROM entities en "
            f"JOIN episode_entities ee ON ee.entity_id = en.id "
            f"JOIN episodes e ON e.id = ee.episode_id "
            f"WHERE en.namespace = ? AND en.name IN ({placeholders}) "
            f"AND e.valid_to IS NULL "
            f"GROUP BY ee.episode_id ORDER BY shared DESC LIMIT ?",
            (namespace, *names, pool),
        ).fetchall()
        return [int(r[0]) for r in rows]

    def _temporal(self, namespace: str, pool: int) -> list[int]:
        rows = self.db.execute(
            "SELECT id FROM episodes WHERE namespace = ? AND valid_to IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (namespace, pool),
        ).fetchall()
        return [int(r[0]) for r in rows]

    def search(
        self, query: str, namespace: str = "default", limit: int = 8, pool: int = 30
    ) -> list[RetrievalResult]:
        channels: dict[str, list[int]] = {
            "vector": self._vector(query, namespace, pool),
            "keyword": self._keyword(query, namespace, pool),
            "graph": self._graph(query, namespace, pool),
            "temporal": self._temporal(namespace, pool),
        }
        scores: dict[int, float] = {}
        contributed: dict[int, list[str]] = {}
        for name, ids in channels.items():
            w = self.weights.get(name, 1.0)
            for rank, eid in enumerate(ids):
                scores[eid] = scores.get(eid, 0.0) + w * (1.0 / (self.rrf_k + rank))
                contributed.setdefault(eid, []).append(name)
        ranked = sorted(scores, key=lambda e: scores[e], reverse=True)[:limit]
        if not ranked:
            return []
        contents = self._contents(ranked)
        return [
            RetrievalResult(
                episode_id=eid,
                content=contents.get(eid, ""),
                score=round(scores[eid], 6),
                channels=contributed.get(eid, []),
            )
            for eid in ranked
        ]

    def _filter_ns_valid(self, ids: list[int], namespace: str) -> list[int]:
        if not ids:
            return []
        keep = {
            int(r[0])
            for r in self.db.execute(
                f"SELECT id FROM episodes WHERE id IN ({','.join('?' * len(ids))}) "
                f"AND namespace = ? AND valid_to IS NULL",
                (*ids, namespace),
            ).fetchall()
        }
        return [i for i in ids if i in keep]

    def _contents(self, ids: list[int]) -> dict[int, str]:
        rows = self.db.execute(
            f"SELECT id, content FROM episodes WHERE id IN ({','.join('?' * len(ids))})",
            tuple(ids),
        ).fetchall()
        return {int(r[0]): r[1] for r in rows}


def _fts_query(text: str) -> str:
    toks = [t for t in _alnum_tokens(text) if len(t) > 1]
    return " OR ".join(toks)


def _alnum_tokens(text: str) -> list[str]:
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
