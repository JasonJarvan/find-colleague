"""职位（1:1）载入：从 data/positions-draft.md 解析草稿 + User 已确认覆盖，写入 colleagues.position。

设计要点：
- 职位是「人」的 1:1 属性，存 colleagues.position（迁移见 db._migrate）。
- 草稿来源 positions-draft.md（gitignored）；User 已确认覆盖那批放在草稿尾部
  `<!-- CONFIRMED -->` 标记后的「已确认职位」表，以其为准（覆盖草稿推断）。
- 本模块**不内联任何真实人名/职位**——全部从 gitignored 的 data/ 草稿解析，
  保证源码可公开发布；真实值随 data/ 保密。
- 只更新 DB 已存在的同事；不新建人（人由周报 ingest 决定）。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

# positions-draft.md 团队表行：| 同事 | 团队 | 推断职位 | 依据 | 置信 |
_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(产品|工程|运营|算法)\s*\|\s*([^|]+?)\s*\|")

# 已确认表行：| 同事 | 确认职位 |（仅在 <!-- CONFIRMED --> 标记之后解析）
_CONFIRMED_MARKER = "<!-- CONFIRMED -->"
_CONFIRMED_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")


def parse_confirmed(md_path: Path) -> dict[str, str]:
    """解析草稿尾部 `<!-- CONFIRMED -->` 之后的「已确认职位」表，返回 {同事: 确认职位}。

    User 拍板的覆盖值存在 gitignored 草稿里（不内联进源码），覆盖团队表的推断职位。
    标记缺失（如旧草稿）时返回空 dict——退化为纯草稿载入，不报错。
    """
    text = md_path.read_text(encoding="utf-8")
    if _CONFIRMED_MARKER not in text:
        return {}
    tail = text.split(_CONFIRMED_MARKER, 1)[1]
    out: dict[str, str] = {}
    for line in tail.splitlines():
        m = _CONFIRMED_ROW.match(line)
        if not m:
            continue
        name, pos = m.group(1).strip(), m.group(2).strip()
        if name in ("同事",) or pos in ("确认职位",) or set(pos) <= {"-"}:
            continue
        out[name] = pos
    return out


def _clean_position(raw: str) -> str:
    """去掉 ⚠️ 标记与首尾空白，保留括注（如「产品经理（偏 GTM/开源）」）。"""
    return raw.replace("⚠️", "").strip()


def parse_draft(md_path: Path) -> dict[str, str]:
    """解析 positions-draft.md 团队表，返回 {同事: 推断职位}。
    跳过「需用户拍板的人」尾表（问题列表，非职位）；遇到「待 review」段即停——
    那批新人草稿尚未经 User 确认，**不灌库**。"""
    out: dict[str, str] = {}
    for line in md_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and "待 review" in line:
            break  # 新人草稿区，未 review，不载入
        m = _ROW.match(line)
        if not m:
            continue
        name, _team, pos = m.group(1).strip(), m.group(2), _clean_position(m.group(3))
        if name in ("同事",) or not pos or pos == "团队":
            continue
        out[name] = pos
    return out


def merge_colleagues(
    conn: sqlite3.Connection, src_name: str, dst_name: str
) -> dict[str, object]:
    """把 src_name 同事合并进 dst_name（以 dst 为准），幂等安全。

    - src 的所有 contributions.colleague_id 改挂到 dst；
    - 删除 src 行；保留 dst 的 position（不动）。
    - colleagues 上只有 contributions 一处外键引用 colleague_id（project_aliases
      引用的是 projects），故只需迁 contributions。
    - 幂等：若 src 已不存在（已合并过），直接返回 merged=False，不报错。
    """
    src = conn.execute(
        "SELECT id FROM colleagues WHERE name = ?", (src_name,)
    ).fetchone()
    dst = conn.execute(
        "SELECT id FROM colleagues WHERE name = ?", (dst_name,)
    ).fetchone()
    if dst is None:
        raise ValueError(f"目标同事不存在: {dst_name}")
    if src is None:
        return {"merged": False, "moved": 0, "reason": f"{src_name} 不存在（可能已合并）"}
    src_id, dst_id = src["id"], dst["id"]
    if src_id == dst_id:
        return {"merged": False, "moved": 0, "reason": "src 与 dst 同一行"}

    moved = conn.execute(
        "UPDATE contributions SET colleague_id = ? WHERE colleague_id = ?",
        (dst_id, src_id),
    ).rowcount
    conn.execute("DELETE FROM colleagues WHERE id = ?", (src_id,))
    conn.commit()
    return {"merged": True, "moved": moved, "src_id": src_id, "dst_id": dst_id}


def load_positions(conn: sqlite3.Connection, md_path: Path) -> dict[str, int]:
    """把草稿 + CONFIRMED 覆盖写进 colleagues.position（只更新 DB 已存在的人）。

    返回统计：drafted（草稿覆盖人数）、confirmed（确认覆盖人数）、
    updated（实际写入 DB 行数）、missing（draft/confirmed 里有但 DB 没有的名字数）。
    """
    drafts = parse_draft(md_path)
    confirmed = parse_confirmed(md_path)
    merged = {**drafts, **confirmed}  # 已确认表覆盖草稿推断
    db_names = {r["name"] for r in conn.execute("SELECT name FROM colleagues")}

    updated = 0
    missing: list[str] = []
    for name, pos in merged.items():
        if name not in db_names:
            missing.append(name)
            continue
        conn.execute("UPDATE colleagues SET position = ? WHERE name = ?", (pos, name))
        updated += 1
    conn.commit()
    return {
        "drafted": len(drafts),
        "confirmed": len(confirmed),
        "updated": updated,
        "missing": len(missing),
    }
