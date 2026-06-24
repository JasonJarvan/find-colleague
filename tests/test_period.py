"""period.py 单元测试：异构 period → ISO 周归一、输入边界解析、跨周交集判定。

零外部依赖，用 stdlib unittest（项目仅依赖 numpy，未引入 pytest）。
跑：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from find_colleague import period as P  # noqa: E402


def wk(y: int, m: int, d: int) -> tuple[int, int]:
    iso = dt.date(y, m, d).isocalendar()
    return (iso[0], iso[1])


class TestParsePeriodToWeeks(unittest.TestCase):
    def test_week_md_single_monday_week(self):
        # 'Week 6.15' → 2026-06-15 是周一 → 仅那一周
        weeks = P.parse_period_to_weeks("Week 6.15")
        self.assertEqual(weeks, {wk(2026, 6, 15)})

    def test_week_md_jan(self):
        weeks = P.parse_period_to_weeks("Week 1.26")
        self.assertEqual(weeks, {wk(2026, 1, 26)})

    def test_date_range_single_week(self):
        # 2026-06-15~06-21 = 周一~周日，单周
        weeks = P.parse_period_to_weeks("2026-06-15~06-21")
        self.assertEqual(weeks, {wk(2026, 6, 15)})

    def test_date_range_spans_two_weeks(self):
        # 2026-06-01~06-14 跨两周（06-01 周一 ~ 06-14 周日）
        weeks = P.parse_period_to_weeks("2026-06-01~06-14")
        self.assertEqual(weeks, {wk(2026, 6, 1), wk(2026, 6, 8)})

    def test_date_range_non_monday_start(self):
        # 2026-02-24（周二）~02-28（周六）→ 落在含 02-24 的那一周
        weeks = P.parse_period_to_weeks("2026-02-24~02-28")
        self.assertEqual(weeks, {wk(2026, 2, 24)})

    def test_date_range_crosses_year(self):
        # 2025-12-29~01-04：结束月(01) < 起始月(12) → 跨年到 2026-01-04
        weeks = P.parse_period_to_weeks("2025-12-29~01-04")
        expected = {wk(2025, 12, 29)} | {wk(2026, 1, 4)}
        self.assertEqual(weeks, expected)

    def test_unparseable_returns_none(self):
        self.assertIsNone(P.parse_period_to_weeks("某个不规范写法"))
        self.assertIsNone(P.parse_period_to_weeks(""))
        self.assertIsNone(P.parse_period_to_weeks(None))


class TestParseBound(unittest.TestCase):
    def test_full_date(self):
        self.assertEqual(P.parse_bound("2026-06-17", as_until=False), dt.date(2026, 6, 17))

    def test_year_month_since_is_first_day(self):
        self.assertEqual(P.parse_bound("2026-06", as_until=False), dt.date(2026, 6, 1))

    def test_year_month_until_is_last_day(self):
        self.assertEqual(P.parse_bound("2026-06", as_until=True), dt.date(2026, 6, 30))
        self.assertEqual(P.parse_bound("2026-02", as_until=True), dt.date(2026, 2, 28))

    def test_iso_week_since_is_monday(self):
        # 2026-W25 的周一
        b = P.parse_bound("2026-W25", as_until=False)
        self.assertEqual(b.isocalendar()[2], 1)  # Monday

    def test_iso_week_until_is_sunday(self):
        b = P.parse_bound("2026-W25", as_until=True)
        self.assertEqual(b.isocalendar()[2], 7)  # Sunday

    def test_bad_bound_raises(self):
        with self.assertRaises(ValueError):
            P.parse_bound("garbage", as_until=False)


class TestWeeksInRange(unittest.TestCase):
    def test_single_day(self):
        d = dt.date(2026, 6, 17)
        self.assertEqual(P.weeks_in_range(d, d), {wk(2026, 6, 17)})

    def test_range_touches_two_weeks(self):
        # 上周日 (06-14) ~ 本周三 (06-17) → 触及 06-08 那周 + 06-15 那周
        weeks = P.weeks_in_range(dt.date(2026, 6, 14), dt.date(2026, 6, 17))
        self.assertEqual(weeks, {wk(2026, 6, 8), wk(2026, 6, 15)})


class TestSelectWeeks(unittest.TestCase):
    def test_since_only_lower_bound(self):
        weeks = P.select_weeks(since="2026-06-15", until=None)
        self.assertIn(wk(2026, 6, 15), weeks)
        self.assertNotIn(wk(2026, 6, 8), weeks)

    def test_until_only_upper_bound(self):
        weeks = P.select_weeks(since=None, until="2026-01-12")
        self.assertIn(wk(2026, 1, 12), weeks)
        self.assertNotIn(wk(2026, 6, 15), weeks)

    def test_none_none_returns_none(self):
        self.assertIsNone(P.select_weeks(since=None, until=None))


class TestPeriodMatchesFilter(unittest.TestCase):
    def test_overlap_passes(self):
        sel = P.select_weeks(since="2026-06-14", until="2026-06-17")  # 两周
        # 'Week 6.8' 落在 06-08 周 → 与所选有交集
        self.assertTrue(P.period_matches("Week 6.8", sel))
        # 'Week 6.15' 落在 06-15 周 → 也有交集
        self.assertTrue(P.period_matches("Week 6.15", sel))

    def test_no_overlap_excluded(self):
        sel = P.select_weeks(since="2026-06-15", until="2026-06-21")  # 仅 06-15 周
        self.assertFalse(P.period_matches("Week 6.1", sel))

    def test_unparseable_excluded_when_filtering(self):
        sel = P.select_weeks(since="2026-06-15", until="2026-06-21")
        self.assertFalse(P.period_matches("不规范", sel))

    def test_everything_passes_without_filter(self):
        # sel=None → 不过滤，连无法解析的也算通过
        self.assertTrue(P.period_matches("Week 6.1", None))
        self.assertTrue(P.period_matches("不规范", None))


if __name__ == "__main__":
    unittest.main()
