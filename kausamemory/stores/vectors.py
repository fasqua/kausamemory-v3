"""Vector channel backed by sqlite-vec (vec0 virtual table).

This replaces v2's approach of holding every vector in a numpy matrix and
rebuilding it on each write. Here vectors live in the same SQLite file and KNN
runs in SIMD C. No RAM matrix, no rebuild-per-write, one portable file.
"""

from __future__ import annotations

import sqlite3

import sqlite_vec


class VectorStore:
    def __init__(self, db: sqlite3.Connection, dim: int) -> None:
        self.db = db
        self.dim = dim
        # vec0 needs a fixed dimension known at table-creation time.
        self.db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_episodes "
            f"USING vec0(embedding float[{dim}] distance_metric=cosine)"
        )
        self.db.commit()

    def add(self, episode_id: int, vector: list[float]) -> None:
        # vec0 rowid == episode id, so we can join back to episodes cheaply.
        self.db.execute(
            "INSERT OR REPLACE INTO vec_episodes(rowid, embedding) VALUES (?, ?)",
            (episode_id, sqlite_vec.serialize_float32(vector)),
        )

    def remove(self, episode_id: int) -> None:
        self.db.execute("DELETE FROM vec_episodes WHERE rowid = ?", (episode_id,))

    def knn(self, query: list[float], k: int = 10) -> list[tuple[int, float]]:
        """Return [(episode_id, distance), ...] nearest first."""
        rows = self.db.execute(
            "SELECT rowid, distance FROM vec_episodes "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (sqlite_vec.serialize_float32(query), k),
        ).fetchall()
        return [(int(r[0]), float(r[1])) for r in rows]
