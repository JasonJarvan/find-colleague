"""召回：结构化过滤 + 向量语义检索（hybrid）。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from . import db
from .config import Config
from .embed import embed_one

# Qwen3-Embedding 非对称检索指令前缀（只加在 query 侧，文档侧不动）
_QWEN3_QUERY_INSTRUCT = "Instruct: 检索从事相关工作的同事\nQuery: {text}"


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


def _embed_query(cfg: Config, text: str) -> np.ndarray:
    """Embed a query string with the Qwen3 instruct prefix."""
    prefixed = _QWEN3_QUERY_INSTRUCT.format(text=text)
    qvec = np.asarray(embed_one(cfg, prefixed), dtype=np.float32)
    qvec = qvec / (np.linalg.norm(qvec) or 1.0)
    return qvec


def _match_projects(conn: sqlite3.Connection, text: str) -> list[str]:
    """返回 query 文本中（包含匹配）命中的项目正则名列表。

    匹配逻辑：遍历所有 projects.name + project_aliases.alias，
    只要某个名字/别名是 query 的子串，就算命中。
    """
    text_lower = text.lower()
    matched: set[str] = set()

    # 按长度降序排列，让更具体的名称优先（避免短串污染）
    rows = conn.execute(
        "SELECT DISTINCT name FROM projects "
        "UNION SELECT a.alias FROM project_aliases a"
    ).fetchall()
    candidates = sorted([r[0] for r in rows], key=len, reverse=True)

    for cand in candidates:
        if cand.lower() in text_lower:
            # 找到该候选对应的规范项目名
            canon_row = conn.execute(
                "SELECT p.name FROM project_aliases a "
                "JOIN projects p ON p.id = a.project_id WHERE a.alias = ?",
                (cand,),
            ).fetchone()
            if canon_row:
                matched.add(canon_row["name"])
            else:
                # cand 本身是 projects.name
                prow = conn.execute(
                    "SELECT name FROM projects WHERE name = ?", (cand,)
                ).fetchone()
                if prow:
                    matched.add(prow["name"])

    return list(matched)


def semantic_query(
    conn: sqlite3.Connection,
    cfg: Config,
    text: str,
    k: int = 8,
    team: str | None = None,
    exclude: set[str] | None = None,
) -> list[Hit]:
    """纯向量语义召回（带 Qwen3 query instruct 前缀）。"""
    where, params = "", ()
    if team:
        where, params = "col.team = ?", (team,)
    recs, mat = _load_matrix(conn, where, params)
    if mat is None:
        return []

    qvec = _embed_query(cfg, text)
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


def hybrid_query(
    conn: sqlite3.Connection,
    cfg: Config,
    text: str,
    k: int = 8,
    team: str | None = None,
    exclude: set[str] | None = None,
) -> list[Hit]:
    """Hybrid 召回：命中已知项目 → 结构化取全部贡献者再向量排序；未命中 → 纯向量。

    这样做的好处：
    - 当 query 明确提到项目名/别名时，结构化精确圈定候选集，避免跨项目干扰；
    - 候选集内再用向量排序，让最相关的子任务贡献者排前。
    - 未命中时退回纯向量，保持模糊语义召回能力。
    """
    exclude = exclude or set()

    matched_projects = _match_projects(conn, text)

    if matched_projects:
        # 结构化路径：取命中项目全部贡献者（并集）
        placeholders = ",".join("?" * len(matched_projects))
        sql_base = (
            "SELECT c.id, col.name AS colleague, col.team, p.name AS project, "
            "       c.summary, c.source_key, c.embedding "
            "FROM contributions c "
            "JOIN colleagues col ON col.id = c.colleague_id "
            "JOIN projects p ON p.id = c.project_id "
            f"WHERE p.name IN ({placeholders}) "
            "AND c.embedding IS NOT NULL"
        )
        params_proj: tuple = tuple(matched_projects)
        if team:
            sql_base += " AND col.team = ?"
            params_proj = params_proj + (team,)

        recs = conn.execute(sql_base, params_proj).fetchall()

        if recs:
            mat = _normalize(np.vstack([db.blob_to_vec(r["embedding"]) for r in recs]))
            qvec = _embed_query(cfg, text)
            sims = mat @ qvec
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

    # 未命中（或命中项目但无带 embedding 的贡献者）→ 纯向量
    return semantic_query(conn, cfg, text, k=k, team=team, exclude=exclude)


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
