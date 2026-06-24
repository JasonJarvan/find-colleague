"""find-colleague CLI —— init / ingest / embed / query / who / projects / positions / people / worklog / models / stats。"""
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


def cmd_positions(args, cfg):
    from .positions import load_positions

    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    stats = load_positions(conn, Path(args.draft))
    print(f"职位载入：{stats}（草稿+已确认覆盖，仅更新 DB 已有同事）")


def cmd_people(args, cfg):
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    persons = recall.people(conn, team=args.team, name=args.name)
    if not persons:
        print("（无匹配同事——检查 --name/--team，或先 ingest 周报）")
        return
    current_team = None
    for p in persons:
        if p.team != current_team:
            current_team = p.team
            print(f"\n## {current_team}团队")
        pos = p.position or "（职位待定）"
        print(f"\n· {p.name}（{p.team}）｜ {pos}")
        if p.works:
            for proj, summary in p.works:
                print(f"    - {proj}：{summary}")
        else:
            print("    （暂无项目记录）")


def cmd_worklog(args, cfg):
    from .period import select_weeks

    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    try:
        select_weeks(args.since, args.until)  # 提前校验边界格式，给清晰报错
    except ValueError as e:
        print(f"时间参数有误：{e}")
        return 2
    groups = recall.worklog(conn, project=args.project, since=args.since, until=args.until)
    if not groups:
        print("（无匹配——检查 --project / 时间范围，或先 ingest 周报）")
        return 0
    span = ""
    if args.since or args.until:
        span = f"（时间：{args.since or '不限'} ~ {args.until or '不限'}，按周展开）"
    for g in groups:
        print(f"\n## {g.project}{span}")
        if g.entries:
            current = None
            for e in g.entries:
                key = (e.colleague, e.team)
                if key != current:
                    current = key
                    print(f"\n· {e.colleague}（{e.team}）")
                print(f"    - 〔{e.period or '未注明'}〕{e.summary}")
        else:
            print("    （所选时间内无记录）")
        if g.unknown_period:
            print("\n  ⚠ 未知时间（period 无法解析，未计入筛选；原文保留）：")
            for e in g.unknown_period:
                print(f"    - {e.colleague}（{e.team}）〔{e.period or '空'}〕{e.summary}")


def cmd_models(args, cfg):
    from .embed import list_models

    for m in list_models(cfg):
        mid = m.get("id") or m.get("name") or m
        print(mid)


_CRAWL_UNAVAILABLE = (
    "crawl 含私域访问逻辑（page/folder id、人名等），未随仓库发布。\n"
    "公开 clone 里 src/find_colleague/crawl.py 缺失属预期；其余命令（ingest/embed/query/who/...）正常可用。\n"
    "如需 refresh：见 docs runbook，或由有权限者本地补 crawl 模块。"
)


def _load_crawl():
    """惰性导入 crawl 模块。缺失（公开 clone）时返回 None，不让整个 CLI import 崩。"""
    try:
        from . import crawl  # noqa: PLC0415
    except ImportError:
        return None
    return crawl


def cmd_crawl(args, cfg):
    crawl = _load_crawl()
    if crawl is None:
        print(_CRAWL_UNAVAILABLE)
        return 2
    if args.plan:
        crawl.plan(space=args.space, since=args.since)
        return 0
    conn = db.connect(cfg.db_path)
    only = [args.only] if args.only else None
    crawl.run(conn, cfg, only=only, dry_run=args.dry_run, no_embed=args.no_embed)
    return 0


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

    ppos = sub.add_parser("positions", help="从 positions-draft.md 把职位载入 colleagues.position")
    ppos.add_argument("--load", action="store_true", help="（默认行为）载入职位草稿 + 已确认覆盖")
    ppos.add_argument("--draft", default=str(REPO_ROOT / "data" / "positions-draft.md"))
    ppos.set_defaults(func=cmd_positions)

    ppl = sub.add_parser("people", help="逐人打印：姓名（团队）｜职位 ｜ 项目→工作清单")
    ppl.add_argument("--team", choices=["产品", "工程", "运营", "算法"])
    ppl.add_argument("--name", help="只看某一个人")
    ppl.set_defaults(func=cmd_people)

    pc = sub.add_parser(
        "crawl",
        help="务实编排：--plan 打印抓取计划；默认 scan data/raw 新快照→抽取→ingest（含私域逻辑，未随仓库发布则降级提示）",
    )
    pc.add_argument("--plan", action="store_true", help="只打印抓取计划（page-id + CQL 模板），不抽取")
    pc.add_argument("--space", default="all", help="--plan 时限定 space（取值见 data/sources.md；默认 all）")
    pc.add_argument("--since", help="--plan 时按年月过滤（YYYY-MM）")
    pc.add_argument("--ingest", action="store_true", help="（默认行为）scan→抽取→ingest")
    pc.add_argument("--only", help="只处理 data/raw 下指定文件名（验证用，省 token）")
    pc.add_argument("--dry-run", action="store_true", help="只扫描列出待抽取文件，不调 LLM、不写库")
    pc.add_argument("--no-embed", action="store_true", help="入库后不补 embedding")
    pc.set_defaults(func=cmd_crawl)

    pwl = sub.add_parser(
        "worklog",
        help="项目视角：项目→人→已做工作（可按周筛时间）。--project 聚焦单项目，省略则全部分组",
    )
    pwl.add_argument("--project", help="聚焦某项目（支持别名；省略则全部项目分组）")
    pwl.add_argument("--since", help="起始（含），YYYY-MM-DD / YYYY-MM / YYYY-Www；按触及的周展开")
    pwl.add_argument("--until", help="截止（含），同上格式")
    pwl.set_defaults(func=cmd_worklog)

    sub.add_parser("models", help="列 OpenRouter 可用 embedding 模型").set_defaults(func=cmd_models)
    sub.add_parser("stats", help="DB 概况").set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    cfg = load_config()
    return args.func(args, cfg) or 0


if __name__ == "__main__":
    sys.exit(main())
