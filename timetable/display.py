"""文本视图渲染：把课表画成能在终端里看的样子。

终端里中文是「双宽字符」，直接 ``ljust`` 会错位，所以这里自己算显示宽度。
"""

from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional, Sequence

from .models import WEEKDAYS, Course, TimeSlot, Timetable, format_duration, format_time

__all__ = [
    "display_width",
    "pad",
    "truncate",
    "render_timetable",
    "render_day_view",
    "render_grid",
]


# --------------------------------------------------------------------------
# 宽度工具
# --------------------------------------------------------------------------
def _char_width(char: str) -> int:
    """单个字符在终端里占几列。"""
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def display_width(text: str) -> int:
    """字符串的终端显示宽度。"""
    return sum(_char_width(ch) for ch in str(text))


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """按显示宽度截断，超长时用省略号收尾。"""
    text = str(text)
    if display_width(text) <= width:
        return text
    budget = width - display_width(ellipsis)
    result, used = "", 0
    for char in text:
        size = _char_width(char)
        if used + size > budget:
            break
        result += char
        used += size
    return result + ellipsis


def pad(text: str, width: int, align: str = "left") -> str:
    """按显示宽度补空格。"""
    text = truncate(text, width)
    filler = " " * max(0, width - display_width(text))
    if align == "right":
        return filler + text
    if align == "center":
        left = len(filler) // 2
        return filler[:left] + text + filler[left:]
    return text + filler


# --------------------------------------------------------------------------
# 本周课表
# --------------------------------------------------------------------------
def _sorted_days(timetable: Timetable) -> List[int]:
    return list(range(7))


def render_day_view(timetable: Timetable, show_empty: bool = True, courses_by_day: Optional[Dict[int, List[Course]]] = None) -> str:
    """「本周课表」的按天列表视图（默认渲染，最直观）。"""
    by_day = courses_by_day if courses_by_day is not None else timetable.courses_by_day()

    lines: List[str] = []
    if timetable.owner:
        lines.append(f"本周课表 · {timetable.owner}")
    lines.append("=" * 52)

    for day in _sorted_days(timetable):
        courses = by_day.get(day, [])
        if not courses:
            if show_empty:
                lines.append("")
                lines.append(f"【{WEEKDAYS[day]}】")
                lines.append("   — 无课 —")
            continue

        total = sum(c.duration for c in courses)
        lines.append("")
        lines.append(f"【{WEEKDAYS[day]}】{len(courses)} 门次，合计 {format_duration(total)}")

        # 先量出这一天里最长的「时间段 + 课程名」，地点统一对齐到它后面
        heads = [f"  {c.slot}  {c.name}" for c in courses]
        column = min(max((display_width(h) for h in heads), default=0) + 2, 48)
        for head, course in zip(heads, courses):
            if course.location:
                lines.append(pad(head, column) + f"@{course.location}")
            else:
                lines.append(head)

    busy = len(timetable.busy_days) if timetable.courses else 0
    lines.append("")
    lines.append("-" * 52)
    lines.append(f"共 {len(timetable)} 门次，分布在 {busy} 天。")
    return "\n".join(lines)


def render_grid(timetable: Timetable, courses_by_day: Optional[Dict[int, List[Course]]] = None, cell_width: int = 12) -> str:
    """周视图：行 = 时间段，列 = 星期。

    时间段来自课表里出现过的所有 ``(开始, 结束)`` 组合，所以不会出现空行。
    """
    by_day = courses_by_day if courses_by_day is not None else timetable.courses_by_day()

    slots: List[TimeSlot] = sorted({course.slot for course in timetable.courses})
    if not slots:
        return f"{timetable.owner or '课表'}：一周都没有课。"

    header = ["时间"] + WEEKDAYS
    widths = [12] + [cell_width] * 7

    lines: List[str] = []
    lines.append(f"周视图 · {timetable.owner}" if timetable.owner else "周视图")
    lines.append(_grid_separator(widths))
    lines.append(_grid_row(header, widths, align="center"))
    lines.append(_grid_separator(widths))

    for slot in slots:
        label = f"{format_time(slot.start)}-{format_time(slot.end)}"
        cells = [label]
        for day in range(7):
            here = [c for c in by_day.get(day, []) if c.start == slot.start and c.end == slot.end]
            if not here:
                cells.append("")
            elif len(here) == 1:
                cells.append(here[0].name)
            else:
                cells.append(f"{here[0].name} 等{len(here)}门")
        lines.append(_grid_row(cells, widths))
        lines.append(_grid_separator(widths))

    return "\n".join(lines)


def _grid_separator(widths: Sequence[int]) -> str:
    return "┼".join("─" * (w + 2) for w in widths)


def _grid_row(cells: Sequence[str], widths: Sequence[int], align: str = "left") -> str:
    return "│".join(" " + pad(cell, width, align) + " " for cell, width in zip(cells, widths))


def render_timetable(timetable: Timetable, mode: str = "day", courses_by_day: Optional[Dict[int, List[Course]]] = None) -> str:
    """统一入口。``mode`` 取 ``"day"``（按天列表）或 ``"grid"``（周视图）。"""
    if mode == "grid":
        return render_grid(timetable, courses_by_day=courses_by_day)
    if mode == "day":
        return render_day_view(timetable, courses_by_day=courses_by_day)
    raise ValueError(f"不认识的展示模式：{mode!r}（可选 day / grid）")
