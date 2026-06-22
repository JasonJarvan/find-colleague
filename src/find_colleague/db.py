"""SQLite schema + 连接。向量以 float32 BLOB 存于 contributions.embedding。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS colleagues (
    id        INTEGER PRIMARY KEY,
    name      TEXT UNIQUE NOT NULL,
    team      TEXT NOT NULL,            -- 产品 | 工程 | 运营 | 算法
    position  TEXT                      -- 1:1 职位（如「全栈工程师」），LLM 推断 + User review 固化
);

CREATE TABLE IF NOT EXISTS projects (
    id    INTEGER PRIMARY KEY,
    name  TEXT UNIQUE NOT NULL          -- 归一项目名
);

CREATE TABLE IF NOT EXISTS project_aliases (
    alias       TEXT PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY,
    key             TEXT UNIQUE NOT NULL,   -- 如 ENG / ALGO
    url             TEXT,
    space           TEXT,
    page_id         TEXT,
    last_crawled_at TEXT
);

CREATE TABLE IF NOT EXISTS contributions (
    id            INTEGER PRIMARY KEY,
    colleague_id  INTEGER NOT NULL REFERENCES colleagues(id),
    project_id    INTEGER NOT NULL REFERENCES projects(id),
    source_key    TEXT,
    period        TEXT,
    summary       TEXT NOT NULL,           -- 角色 / 做了什么
    embed_text    TEXT,                    -- 实际送 embedding 的文本
    embedding     BLOB                     -- float32 向量
);

CREATE TABLE IF NOT EXISTS crawl_log (
    page_id      TEXT PRIMARY KEY,
    fetched_at   TEXT,
    content_hash TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_contrib_colleague ON contributions(colleague_id);
CREATE INDEX IF NOT EXISTS idx_contrib_project   ON contributions(project_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """幂等迁移：旧库 colleagues 无 position 列时补上。CREATE TABLE IF NOT EXISTS
    不会改既有表，故老库要靠 ALTER TABLE 补列。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(colleagues)")}
    if "position" not in cols:
        conn.execute("ALTER TABLE colleagues ADD COLUMN position TEXT")


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def vec_to_blob(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
