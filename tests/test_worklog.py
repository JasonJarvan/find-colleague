"""recall.worklog 集成测试：内存 DB，纯 SQL + 周筛选，无 LLM/embedding。

跑：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from find_colleague import db, recall  # noqa: E402


def _seed() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.executescript(
        """
        INSERT INTO colleagues(id,name,team,position) VALUES
            (1,'甲','工程','后端'),
            (2,'乙','算法','算法工程师'),
            (3,'丙','产品','PM');
        INSERT INTO projects(id,name) VALUES (1,'Alpha'),(2,'Beta');
        INSERT INTO project_aliases(alias,project_id) VALUES ('阿尔法',1);
        INSERT INTO contributions(id,colleague_id,project_id,source_key,period,summary) VALUES
            (1,1,1,'ENG','Week 6.15','搭后端'),
            (2,2,1,'ALGO','2026-06-01~06-14','调模型'),
            (3,3,2,'PROD','Week 6.22','写需求'),
            (4,1,1,'ENG','不规范时间','早期工作');
        """
    )
    conn.commit()
    return conn


class TestWorklog(unittest.TestCase):
    def test_all_projects_no_filter(self):
        conn = _seed()
        out = recall.worklog(conn)
        names = [pw.project for pw in out]
        self.assertEqual(names, ["Alpha", "Beta"])  # 按项目名排序
        alpha = out[0]
        # 无筛选：4 条里 Alpha 占 3 条全部计入 entries，unknown 桶为空
        self.assertEqual(len(alpha.entries), 3)
        self.assertEqual(alpha.unknown_period, [])

    def test_focus_single_project_by_alias(self):
        conn = _seed()
        out = recall.worklog(conn, project="阿尔法")  # 别名归一到 Alpha
        self.assertEqual([pw.project for pw in out], ["Alpha"])

    def test_time_filter_includes_touched_weeks(self):
        conn = _seed()
        # 仅 06-15 那一周
        out = recall.worklog(conn, since="2026-06-15", until="2026-06-21")
        alpha = next(pw for pw in out if pw.project == "Alpha")
        periods = {e.period for e in alpha.entries}
        # Week 6.15 命中；2026-06-01~06-14（06-01/06-08 周）不命中
        self.assertIn("Week 6.15", periods)
        self.assertNotIn("2026-06-01~06-14", periods)
        # Beta 的 Week 6.22 不在范围 → Beta 整组不出现（无 entries 无 unknown）
        self.assertNotIn("Beta", [pw.project for pw in out])

    def test_range_expands_to_multiple_weeks(self):
        conn = _seed()
        # 06-08~06-15 触及 06-08 周 + 06-15 周
        out = recall.worklog(conn, since="2026-06-08", until="2026-06-15")
        alpha = next(pw for pw in out if pw.project == "Alpha")
        periods = {e.period for e in alpha.entries}
        self.assertIn("Week 6.15", periods)            # 06-15 周
        self.assertIn("2026-06-01~06-14", periods)     # 含 06-08 周

    def test_unparseable_period_bucketed_when_filtering(self):
        conn = _seed()
        out = recall.worklog(conn, since="2026-06-15", until="2026-06-21")
        alpha = next(pw for pw in out if pw.project == "Alpha")
        unknown = {e.period for e in alpha.unknown_period}
        self.assertIn("不规范时间", unknown)            # 没静默丢弃
        # 且不混进正常 entries
        self.assertNotIn("不规范时间", {e.period for e in alpha.entries})


if __name__ == "__main__":
    unittest.main()
