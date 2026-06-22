"""find-colleague CLI —— init / ingest / embed / query / who / projects / models / stats。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, recall
from .config import REPO_ROOT, load_config
from .ingest import embed_pending, ingest_json, ingest_md

DEFAULT_MD = REPO_ROOT / "data" / "colleague-project.md"
DEFAULT_JSON = REPO_ROOT / "data" / "extracted" / "records.json"


def _print_hits(hits, show_score: bool) -> None:
    if not hits:
        print("（数据中未见匹配——可换个说法，或先 refresh 抓最新周报）")
        return
    for h in hits:
        score = f"  [{h.score:.3f}]" if show_score else ""
        print(f"· {h.colleague}（{h.team}）— {h.project}：{h.summary} 〔{h.source}〕{score}")


def cmd_init(args, cfg):
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    print(f"已初始化 DB：{cfg.db_path}")


def cmd_ingest(args, cfg):
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    if args.from_json:
        stats = ingest_json(conn, Path(args.from_json))
        print(f"从抽取 JSON 入库：{stats}")
    else:
        stats = ingest_md(conn, Path(args.md))
        print(f"从 MD 解析入库：{stats}")
    if args.no_embed:
        print("已跳过 embedding（--no-embed）。补向量请跑：find-colleague embed")
        return
    n = embed_pending(conn, cfg)
    print(f"embedding 完成：{n} 条（模型 {cfg.embed_model}）")


def cmd_embed(args, cfg):
    conn = db.connect(cfg.db_path)
    n = embed_pending(conn, cfg)
    print(f"补 embedding：{n} 条" if n else "无待补向量。")


def cmd_query(args, cfg):
    conn = db.connect(cfg.db_path)
    exclude = {args.exclude} if args.exclude else set()
    hits = recall.hybrid_query(conn, cfg, args.text, k=args.k, team=args.team, exclude=exclude)
    _print_hits(hits, show_score=True)


def cmd_who(args, cfg):
    conn = db.connect(cfg.db_path)
    exclude = {args.exclude} if args.exclude else set()
    hits = recall.who_on_project(conn, args.project, exclude=exclude)
    _print_hits(hits, show_score=False)


def cmd_projects(args, cfg):
    conn = db.connect(cfg.db_path)
    _print_hits(recall.projects_of(conn, args.name), show_score=False)


def cmd_models(args, cfg):
    from .embed import list_models

    for m in list_models(cfg):
        mid = m.get("id") or m.get("name") or m
        print(mid)


def cmd_stats(args, cfg):
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    c = lambda q: conn.execute(q).fetchone()[0]
    print(f"colleagues : {c('SELECT COUNT(*) FROM colleagues')}")
    print(f"projects   : {c('SELECT COUNT(*) FROM projects')}")
    print(f"aliases    : {c('SELECT COUNT(*) FROM project_aliases')}")
    print(f"contrib    : {c('SELECT COUNT(*) FROM contributions')}")
    print(f"embedded   : {c('SELECT COUNT(*) FROM contributions WHERE embedding IS NOT NULL')}")
    print(f"embed_model: {db.get_meta(conn, 'embed_model')}  dim: {db.get_meta(conn, 'embed_dim')}")
    print("teams      :")
    for r in conn.execute("SELECT team, COUNT(*) n FROM colleagues GROUP BY team"):
        print(f"  {r['team']}: {r['n']}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="find-colleague", description="根据项目找负责的同事（v2: SQLite+向量）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建表").set_defaults(func=cmd_init)

    pi = sub.add_parser("ingest", help="入库 + embedding（默认从 MD；--from-json 吃抽取产物）")
    pi.add_argument("--md", default=str(DEFAULT_MD))
    pi.add_argument("--from-json", nargs="?", const=str(DEFAULT_JSON), default=None,
                    help="从抽取 JSON 入库（省略路径默认 data/extracted/records.json）")
    pi.add_argument("--no-embed", action="store_true", help="只入库，不调 embedding")
    pi.set_defaults(func=cmd_ingest)

    sub.add_parser("embed", help="给缺向量的记录补 embedding").set_defaults(func=cmd_embed)

    pq = sub.add_parser("query", help="语义召回：该找谁")
    pq.add_argument("text")
    pq.add_argument("-k", type=int, default=8)
    pq.add_argument("--team", choices=["产品", "工程", "运营", "算法"])
    pq.add_argument("--exclude", help="排除某人（通常是提问者本人）")
    pq.set_defaults(func=cmd_query)

    pw = sub.add_parser("who", help="结构化：某项目该找谁")
    pw.add_argument("project")
    pw.add_argument("--exclude")
    pw.set_defaults(func=cmd_who)

    pp = sub.add_parser("projects", help="某同事在做哪些项目")
    pp.add_argument("name")
    pp.set_defaults(func=cmd_projects)

    sub.add_parser("models", help="列 OpenRouter 可用 embedding 模型").set_defaults(func=cmd_models)
    sub.add_parser("stats", help="DB 概况").set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    cfg = load_config()
    return args.func(args, cfg) or 0


if __name__ == "__main__":
    sys.exit(main())
