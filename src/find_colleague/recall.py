"""召回：结构化过滤 + 向量语义检索（hybrid）。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from . import db
from .config import Config
from .embed import embed_one


@dataclass
class Hit:
    colleague: str
    team: str
    project: str
    summary: str
    source: str
    score: float


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


def _load_matrix(conn: sqlite3.Connection, where: str = "", params: tuple = ()):
    sql = (
        "SELECT c.id, col.name AS colleague, col.team, p.name AS project, "
        "       c.summary, c.source_key, c.embedding "
        "FROM contributions c "
        "JOIN colleagues col ON col.id = c.colleague_id "
        "JOIN projects p ON p.id = c.project_id "
        "WHERE c.embedding IS NOT NULL "
    )
    if where:
        sql += f"AND {where} "
    recs = conn.execute(sql, params).fetchall()
    if not recs:
        return [], None
    mat = np.vstack([db.blob_to_vec(r["embedding"]) for r in recs])
    return recs, _normalize(mat)


def semantic_query(
    conn: sqlite3.Connection,
    cfg: Config,
    text: str,
    k: int = 8,
    team: str | None = None,
    exclude: set[str] | None = None,
) -> list[Hit]:
    where, params = "", ()
    if team:
        where, params = "col.team = ?", (team,)
    recs, mat = _load_matrix(conn, where, params)
    if mat is None:
        return []

    qvec = np.asarray(embed_one(cfg, text), dtype=np.float32)
    qvec = qvec / (np.linalg.norm(qvec) or 1.0)
    sims = mat @ qvec

    exclude = exclude or set()
    order = np.argsort(-sims)
    hits: list[Hit] = []
    for idx in order:
        r = recs[idx]
        if r["colleague"] in exclude:
            continue
        hits.append(
            Hit(r["colleague"], r["team"], r["project"], r["summary"],
                r["source_key"] or "", float(sims[idx]))
        )
        if len(hits) >= k:
            break
    return hits


def who_on_project(conn: sqlite3.Connection, query: str, exclude: set[str] | None = None) -> list[Hit]:
    """结构化：项目名/别名 → 同事。先精确/别名命中，否则 LIKE 模糊。"""
    exclude = exclude or set()
    # 别名归一
    canon = conn.execute(
        "SELECT p.name FROM project_aliases a JOIN projects p ON p.id = a.project_id "
        "WHERE a.alias = ?",
        (query,),
    ).fetchone()
    if canon:
        pname = canon["name"]
        rows = conn.execute(
            "SELECT col.name colleague, col.team, p.name project, c.summary, c.source_key "
            "FROM contributions c JOIN colleagues col ON col.id=c.colleague_id "
            "JOIN projects p ON p.id=c.project_id WHERE p.name = ?",
            (pname,),
        ).fetchall()
    else:
        like = f"%{query}%"
        rows = conn.execute(
            "SELECT col.name colleague, col.team, p.name project, c.summary, c.source_key "
            "FROM contributions c JOIN colleagues col ON col.id=c.colleague_id "
            "JOIN projects p ON p.id=c.project_id "
            "WHERE p.name LIKE ? OR c.summary LIKE ?",
            (like, like),
        ).fetchall()
    return [
        Hit(r["colleague"], r["team"], r["project"], r["summary"], r["source_key"] or "", 1.0)
        for r in rows
        if r["colleague"] not in exclude
    ]


def projects_of(conn: sqlite3.Connection, name: str) -> list[Hit]:
    rows = conn.execute(
        "SELECT col.name colleague, col.team, p.name project, c.summary, c.source_key "
        "FROM contributions c JOIN colleagues col ON col.id=c.colleague_id "
        "JOIN projects p ON p.id=c.project_id WHERE col.name = ?",
        (name,),
    ).fetchall()
    return [Hit(r["colleague"], r["team"], r["project"], r["summary"], r["source_key"] or "", 1.0) for r in rows]
