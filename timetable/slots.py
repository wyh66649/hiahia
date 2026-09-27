"""空闲时段计算（需求 2）。

需求原文：

    给定每天的可用时间范围（如 08:00—22:00），算出每天的空闲时段；
    能把同一课程连续两节合并显示，不要出现 09:00-09:45、09:55-10:40 这种碎片。

这里的「碎片」是怎么来的
------------------------
大学一节课常见排法是「两节连上、中间休息 10 分钟」，导出到 CSV 里就变成两条独立记录::

    高等数学,周一,09:00,09:45
    高等数学,周一,09:55,10:40

如果不处理，算空闲时会认成「09:00-09:45 有课、09:45-09:55 空闲、09:55-10:40 有课」，
凭空多出一个只有 10 分钟、根本没法用的「空闲时段」。

所以本模块的第一步是 :func:`merge_courses`：**把同一门课、同一天、间隔不超过
``max_gap``（默认 15 分钟）的相邻节次并成一条**，再拿合并后的整块去算空闲。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from .models import (
    Course,
    TimeSlot,
    Timetable,
    format_duration,
    format_time,
    merge_intervals,
    weekday_name,
)

__all__ = [
    "DEFAULT_MERGE_GAP",
    "DEFAULT_DAY_START",
    "DEFAULT_DAY_END",
    "merge_courses",
    "merged_courses_by_day",
    "busy_slots",
    "free_slots",
    "daily_free_slots",
    "render_free_slots",
]

#: 同一门课两节之间不超过这么多分钟，就认为它们是「连续两节」，合并成一块
DEFAULT_MERGE_GAP = 15

#: 默认的每日可用时间范围 08:00
DEFAULT_DAY_START = 8 * 60
#: 默认的每日可用时间范围 22:00
DEFAULT_DAY_END = 22 * 60


# --------------------------------------------------------------------------
# 合并连续节次
# --------------------------------------------------------------------------
def merge_courses(courses: Iterable[Course], max_gap: int = DEFAULT_MERGE_GAP) -> List[Course]:
    """把「同一门课 + 同一天 + 间隔 ≤ max_gap」的相邻节次合并成一条。

    只合并**同名课程**：两门不同的课挨在一起（比如 09:00-10:00 高数、
    10:00-11:00 英语）不该被合成一条，它们是两门课。

    >>> from timetable.models import Course
    >>> cs = [Course("高等数学", 0, 540, 585), Course("高等数学", 0, 595, 640)]
    >>> [str(c.slot) for c in merge_courses(cs)]
    ['09:00-10:40']
    >>> other = [Course("高等数学", 0, 540, 585), Course("大学英语", 0, 595, 640)]
    >>> [c.name for c in merge_courses(other)]
    ['高等数学', '大学英语']
    """
    result: List[Course] = []

    for weekday in range(7):
        today = sorted(
            (c for c in courses if c.weekday == weekday),
            key=lambda c: (c.start, c.end, c.name),
        )
        if not today:
            continue

        # 按课程名分组，保持首次出现的顺序，便于输出稳定
        grouped: Dict[str, List[Course]] = {}
        for course in today:
            grouped.setdefault(course.name, []).append(course)

        for name, items in grouped.items():
            current = items[0]
            for nxt in items[1:]:
                if nxt.start - current.end <= max_gap:
                    # 相邻（或重叠）就并成一块，时间取并集
                    current = current.with_slot(current.slot.merge(nxt.slot))
                else:
                    result.append(current)
                    current = nxt
            result.append(current)

    return sorted(result, key=lambda c: (c.weekday, c.start, c.end, c.name))


# --------------------------------------------------------------------------
# 占用 / 空闲
# --------------------------------------------------------------------------
def merged_courses_by_day(
    timetable: Timetable, max_gap: int = DEFAULT_MERGE_GAP
) -> Dict[int, List[Course]]:
    """合并连续节次后的 ``{星期序号: [课程, ...]}``，直接喂给 ``display`` 渲染。"""
    return {
        weekday: merge_courses(timetable.courses_on(weekday), max_gap=max_gap)
        for weekday in range(7)
    }


def busy_slots(courses: Iterable[Course], max_gap: int = DEFAULT_MERGE_GAP) -> List[TimeSlot]:
    """某一天真正被占用的时间段（合并连续节次后再取并集，已排序）。"""
    merged = merge_courses(courses, max_gap=max_gap)
    return merge_intervals([course.slot for course in merged])


def free_slots(
    busy: Sequence[TimeSlot],
    day_start: int = DEFAULT_DAY_START,
    day_end: int = DEFAULT_DAY_END,
) -> List[TimeSlot]:
    """在 ``[day_start, day_end)`` 里挖掉被占用的部分，剩下的就是空闲时段。"""
    if day_start >= day_end:
        raise ValueError(
            f"可用时间范围非法：{format_time(day_start)}-{format_time(day_end)}"
        )

    result: List[TimeSlot] = []
    cursor = day_start
    for slot in sorted(busy):
        clipped = slot.slice(day_start, day_end)
        if clipped is None:
            continue
        if clipped.start > cursor:
            result.append(TimeSlot(cursor, clipped.start))
        cursor = max(cursor, clipped.end)

    if cursor < day_end:
        result.append(TimeSlot(cursor, day_end))
    return result


def daily_free_slots(
    timetable: Timetable,
    day_start: int = DEFAULT_DAY_START,
    day_end: int = DEFAULT_DAY_END,
    merge: bool = True,
    max_gap: int = DEFAULT_MERGE_GAP,
    min_minutes: int = 0,
) -> Dict[int, List[TimeSlot]]:
    """算出整周的每日空闲时段，返回 ``{星期序号: [空闲时段, ...]}``。

    :param merge: 是否合并同一课程的连续节次。关掉的话就能看到 09:45-09:55
        那种碎片 —— 保留这个开关只是为了让对比效果看得见。
    :param min_minutes: 过滤掉短于这个长度的空闲时段，默认 0（全部都留）。
    """
    result: Dict[int, List[TimeSlot]] = {}
    for weekday in range(7):
        courses = timetable.courses_on(weekday)
        if merge:
            busy = busy_slots(courses, max_gap=max_gap)
        else:
            busy = merge_intervals([course.slot for course in courses])
        slots = free_slots(busy, day_start, day_end)
        result[weekday] = [s for s in slots if s.duration >= min_minutes]
    return result


# --------------------------------------------------------------------------
# 文本输出
# --------------------------------------------------------------------------
def render_free_slots(
    timetable: Timetable,
    free_by_day: Optional[Dict[int, List[TimeSlot]]] = None,
    day_start: int = DEFAULT_DAY_START,
    day_end: int = DEFAULT_DAY_END,
    show_empty: bool = True,
) -> str:
    """把每日空闲时段渲染成文本视图。"""
    if free_by_day is None:
        free_by_day = daily_free_slots(timetable, day_start, day_end)

    lines: List[str] = []
    title = f"{timetable.owner} 的空闲时段" if timetable.owner else "空闲时段"
    lines.append(f"{title}（每日可用 {format_time(day_start)} - {format_time(day_end)}）")
    lines.append("=" * 52)

    total = 0
    for weekday in range(7):
        slots = free_by_day.get(weekday, [])
        if not slots and not show_empty:
            continue
        lines.append("")
        if not slots:
            lines.append(f"【{weekday_name(weekday)}】")
            lines.append("   — 全被占满，没有空闲 —")
            continue
        day_total = sum(slot.duration for slot in slots)
        total += day_total
        lines.append(
            f"【{weekday_name(weekday)}】{len(slots)} 段空闲，合计 {format_duration(day_total)}"
        )
        for slot in slots:
            lines.append(f"  {slot}    {format_duration(slot.duration)}")

    lines.append("")
    lines.append("-" * 52)
    if len(free_by_day) == 1:
        only = next(iter(free_by_day))
        lines.append(f"{weekday_name(only)}空闲合计 {format_duration(total)}。")
    else:
        lines.append(f"全周空闲合计 {format_duration(total)}。")
    return "\n".join(lines)
