"""SQLite schema and connection helper.

Principle: the episode (verbatim text) is the source of truth. Vectors, the FTS
index, and the entity graph are all derived indexes built on top of episodes.
Carried over from v2 as ideas (not its code): FTS5, bi-temporal columns
(valid_from / valid_to / superseded_by), namespace isolation, WAL mode.
"""

from __future__ import annotations

import sqlite3
import time

import sqlite_vec

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS episodes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace     TEXT    NOT NULL DEFAULT 'default',
    content       TEXT    NOT NULL,               -- stored verbatim, never rewritten
    role          TEXT,                            -- optional: user / assistant / note
    created_at    REAL    NOT NULL,
    valid_from    REAL,
    valid_to      REAL,                            -- NULL = currently valid
    superseded_by INTEGER,                         -- id of the newer episode
    last_access   REAL,
    access_count  INTEGER NOT NULL DEFAULT 0,
    expires_at    REAL,                            -- NULL = no TTL
    meta          TEXT                             -- JSON blob, arbitrary metadata
);
CREATE INDEX IF NOT EXISTS idx_ep_ns    ON episodes(namespace);
CREATE INDEX IF NOT EXISTS idx_ep_valid ON episodes(valid_to);
CREATE INDEX IF NOT EXISTS idx_ep_time  ON episodes(created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    content, content='episodes', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS ep_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS ep_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, content) VALUES('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS ep_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO episodes_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS entities (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace  TEXT NOT NULL DEFAULT 'default',
    name       TEXT NOT NULL,
    kind       TEXT,
    created_at REAL NOT NULL,
    UNIQUE(namespace, name)
);
CREATE TABLE IF NOT EXISTS episode_entities (
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (episode_id, entity_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    seq        INTEGER PRIMARY KEY,               -- monotonic; matches head seq
    cid        TEXT NOT NULL,                      -- blake3:<hex> of encrypted blob
    created_at REAL NOT NULL,
    locator    TEXT
);
"""


def connect(path: str) -> sqlite3.Connection:
    """Open a connection with sqlite-vec loaded and the schema applied."""
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.executescript(SCHEMA)
    db.commit()
    return db


def now() -> float:
    return time.time()
