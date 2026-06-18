"""入库：①从 colleague-project.md 确定性解析（v1 数据）②从抽取 JSON 入库（爬取管线产物）；
embedding 单独一步。"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import db
from .config import Config
from .embed import embed_texts

TEAM_KEYWORDS = ["产品", "工程", "运营", "算法"]


@dataclass
class Row:
    colleague: str
    team: str
    project: str
    summary: str
    source: str


def _split_md_row(line: str) -> list[str] | None:
    """解析 markdown 表格行 `| a | b | c | d |` → [a,b,c,d]；非表格行返回 None。"""
    s = line.strip()
    if not s.startswith("|"):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    return cells


def _team_from_header(header: str) -> str | None:
    for kw in TEAM_KEYWORDS:
        if kw in header:
            return kw
    return None


def parse_md(md_path: Path) -> tuple[list[Row], dict[str, str]]:
    """返回 (主映射表行, 别名->归一项目名)。纯解析，无网络。"""
    rows: list[Row] = []
    aliases: dict[str, str] = {}

    current_team: str | None = None
    in_alias_table = False
    text = md_path.read_text(encoding="utf-8")

    for line in text.splitlines():
        stripped = line.strip()

        # 别名表区段（## 项目别名表）
        if stripped.startswith("## "):
            in_alias_table = "项目别名表" in stripped
            current_team = None  # 离开主映射表的任何 ### section
            continue

        # 团队 section（### xx团队）只在主映射表 h2 之后有效
        if stripped.startswith("### "):
            current_team = _team_from_header(stripped)
            continue

        cells = _split_md_row(line)
        if cells is None:
            continue
        # 跳过表头与分隔行
        if not cells or set("".join(cells)) <= set("-: "):
            continue

        if in_alias_table and len(cells) >= 2 and cells[0] not in ("归一项目名",):
            canon = cells[0]
            for alias in re.split(r"[、,，]", cells[1]):
                alias = alias.split("（")[0].strip()  # 去掉 "（均属…）" 之类括注
                if alias:
                    aliases[alias] = canon
            aliases.setdefault(canon, canon)  # 归一名也映射到自身
            continue

        if current_team and len(cells) == 4 and cells[0] != "同事":
            colleague, project, summary, source = cells
            if colleague and project:
                rows.append(Row(colleague, current_team, project, summary, source))

    return rows, aliases


def _persist_rows(conn: sqlite3.Connection, rows: list[dict], aliases: dict[str, str]) -> dict[str, int]:
    """把 rows（dict: colleague/team/project/summary/source/embed_text）写库。全量替换 contributions。"""
    conn.execute("DELETE FROM contributions")

    for r in rows:
        conn.execute(
            "INSERT INTO colleagues(name, team) VALUES(?, ?) "
            "ON CONFLICT(name) DO UPDATE SET team = excluded.team",
            (r["colleague"], r["team"]),
        )
    canon_names = set(aliases.values()) | {r["project"] for r in rows}
    for name in canon_names:
        conn.execute("INSERT OR IGNORE INTO projects(name) VALUES(?)", (name,))
    for alias, canon in aliases.items():
        conn.execute("INSERT OR IGNORE INTO projects(name) VALUES(?)", (canon,))
        pid = conn.execute("SELECT id FROM projects WHERE name = ?", (canon,)).fetchone()
        conn.execute(
            "INSERT INTO project_aliases(alias, project_id) VALUES(?, ?) "
            "ON CONFLICT(alias) DO UPDATE SET project_id = excluded.project_id",
            (alias, pid["id"]),
        )

    def proj_id(name: str) -> int:
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        canon = aliases.get(name, name)
        conn.execute("INSERT OR IGNORE INTO projects(name) VALUES(?)", (canon,))
        return conn.execute("SELECT id FROM projects WHERE name = ?", (canon,)).fetchone()["id"]

    n = 0
    for r in rows:
        cid = conn.execute("SELECT id FROM colleagues WHERE name = ?", (r["colleague"],)).fetchone()["id"]
        pid = proj_id(r["project"])
        embed_text = r.get("embed_text") or f"{r['project']}：{r['summary']}（{r['colleague']}，{r['team']}）"
        conn.execute(
            "INSERT INTO contributions(colleague_id, project_id, source_key, period, summary, embed_text) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (cid, pid, r.get("source"), r.get("period"), r["summary"], embed_text),
        )
        n += 1
    conn.commit()
    return {
        "contributions": n,
        "colleagues": conn.execute("SELECT COUNT(*) c FROM colleagues").fetchone()["c"],
        "projects": conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"],
        "aliases": conn.execute("SELECT COUNT(*) c FROM project_aliases").fetchone()["c"],
    }


def ingest_md(conn: sqlite3.Connection, md_path: Path) -> dict[str, int]:
    """从 colleague-project.md 确定性解析入库（v1 数据，embed_text 机械拼接，无富化）。"""
    rows, aliases = parse_md(md_path)
    dict_rows = [
        {"colleague": r.colleague, "team": r.team, "project": r.project,
         "summary": r.summary, "source": r.source}
        for r in rows
    ]
    return _persist_rows(conn, dict_rows, aliases)


def ingest_json(conn: sqlite3.Connection, json_path: Path) -> dict[str, int]:
    """从抽取 JSON 入库（subagent / v3 service 产物）。schema 见 prompts/extract.md。"""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    records = data.get("records", [])
    aliases = data.get("aliases", {})
    for canon in list(aliases.values()):
        aliases.setdefault(canon, canon)
    return _persist_rows(conn, records, aliases)


def embed_pending(conn: sqlite3.Connection, cfg: Config) -> int:
    """给 embedding 为空的 contributions 补向量。返回处理条数。"""
    pending = conn.execute(
        "SELECT id, embed_text FROM contributions WHERE embedding IS NULL"
    ).fetchall()
    if not pending:
        return 0
    texts = [p["embed_text"] for p in pending]
    vecs = embed_texts(cfg, texts)
    for p, v in zip(pending, vecs):
        conn.execute(
            "UPDATE contributions SET embedding = ? WHERE id = ?",
            (db.vec_to_blob(v), p["id"]),
        )
    db.set_meta(conn, "embed_model", cfg.embed_model)
    if vecs:
        db.set_meta(conn, "embed_dim", str(len(vecs[0])))
    conn.commit()
    return len(pending)
