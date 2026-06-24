"""异构 period 字段 → ISO 周（周一起始）归一 + 时间筛选边界解析。

业务约定：粒度=周，周一为一周起始（每周一写周报）。输入范围按「触及的周」展开。
period 历史写法异构，详见 docs/adr/0001-period-to-week-normalization.md。

周键 = ISO 周 (year, week)，由 date.isocalendar() 得到，天然周一为界、跨年自洽。
纯函数、零外部依赖（仅 stdlib）。
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

# 数据集年份基准：'Week M.D' 不含年份，按当前数据集年份解释（见 ADR-0001 已知边界）。
_DATA_YEAR = 2026

Week = tuple[int, int]  # (iso_year, iso_week)

_WEEK_MD = re.compile(r"^\s*Week\s+(\d{1,2})\.(\d{1,2})\s*$", re.IGNORECASE)
# YYYY-MM-DD~MM-DD（结束部分只给月日）
_RANGE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*~\s*(\d{1,2})-(\d{1,2})\s*$")


def _week_of(d: dt.date) -> Week:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def _weeks_between(start: dt.date, end: dt.date) -> set[Week]:
    """收集 [start, end]（含端点）覆盖的全部 ISO 周。start>end 时自动交换。"""
    if start > end:
        start, end = end, start
    weeks: set[Week] = set()
    d = start
    while d <= end:
        weeks.add(_week_of(d))
        d += dt.timedelta(days=1)
    return weeks


def parse_period_to_weeks(period: str | None) -> set[Week] | None:
    """把一条 contribution 的 period 映射到它覆盖的 ISO 周集合。

    无法解析 → None（调用方据此走「未知时间」策略，不静默丢弃）。
    """
    if not period:
        return None
    text = period.strip()

    m = _WEEK_MD.match(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            d = dt.date(_DATA_YEAR, month, day)
        except ValueError:
            return None
        return {_week_of(d)}

    m = _RANGE.match(text)
    if m:
        y, m1, d1, m2, d2 = (int(g) for g in m.groups())
        try:
            start = dt.date(y, m1, d1)
            # 结束月份小于起始月份 → 跨年到下一年
            end_year = y + 1 if m2 < m1 else y
            end = dt.date(end_year, m2, d2)
        except ValueError:
            return None
        return _weeks_between(start, end)

    return None


def parse_bound(s: str, *, as_until: bool) -> dt.date:
    """把一个筛选边界字符串解析成具体日期。

    支持三种格式：
      - YYYY-MM-DD：该日。
      - YYYY-MM：as_until=False 取该月首日，as_until=True 取该月末日。
      - YYYY-Www（ISO 周）：as_until=False 取该周周一，as_until=True 取该周周日。
    无法解析 → ValueError。
    """
    s = s.strip()

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        return dt.date(y, mo, d)

    m = re.fullmatch(r"(\d{4})-W(\d{1,2})", s, re.IGNORECASE)
    if m:
        y, w = int(m.group(1)), int(m.group(2))
        monday = dt.date.fromisocalendar(y, w, 1)
        return monday + dt.timedelta(days=6) if as_until else monday

    m = re.fullmatch(r"(\d{4})-(\d{1,2})", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if as_until:
            last = calendar.monthrange(y, mo)[1]
            return dt.date(y, mo, last)
        return dt.date(y, mo, 1)

    raise ValueError(
        f"无法解析时间边界 {s!r}；支持 YYYY-MM-DD / YYYY-MM / YYYY-Www"
    )


def weeks_in_range(start: dt.date, end: dt.date) -> set[Week]:
    """输入日期区间 [start, end] 触及的全部 ISO 周。"""
    return _weeks_between(start, end)


def select_weeks(since: str | None, until: str | None) -> set[Week] | None:
    """把 --since/--until 解析成「所选周集合」。

    - 都为 None → None（不过滤）。
    - 只给一端 → 另一端取数据上下界（用极早/极晚日期兜住，只设单边界）。
    """
    if since is None and until is None:
        return None
    lo = parse_bound(since, as_until=False) if since else dt.date(1970, 1, 1)
    hi = parse_bound(until, as_until=True) if until else dt.date(2999, 12, 31)
    return weeks_in_range(lo, hi)


def period_matches(period: str | None, selected: set[Week] | None) -> bool:
    """contribution 是否通过时间筛选。

    - selected=None（无筛选）→ 一律通过（含无法解析的 period）。
    - 有筛选：period 覆盖的周与所选周有交集才通过；无法解析的 period 一律不通过
      （由调用方汇总到「未知时间」桶展示，不静默丢弃）。
    """
    if selected is None:
        return True
    weeks = parse_period_to_weeks(period)
    if weeks is None:
        return False
    return not weeks.isdisjoint(selected)
