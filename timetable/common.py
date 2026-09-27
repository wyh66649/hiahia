"""多份课表的共同空闲时间（需求 3）。

需求原文：

    输入多个人的课表，算出所有人的共同空闲时段；结果按「越长越靠前」排序。

算法很简单直白：**先各自求空闲，再逐天求交集**。

1. 每个人单独按需求 2 的规则算出每日空闲时段（含连续节次合并）；
2. 对每天，把所有人的空闲时段列表两两取交集，得到的才是「所有人都空着」的时间；
3. 汇总成一张表，按空闲时长**从长到短**排序，长度相同的按星期、开始时间排。

之所以先各算各的再取交集，而不是把所有人的课摞在一起当一张课表算，
是因为「共同空闲」的语义是 *所有人都空着*，而不是 *没有人上课* ——
后者会把「甲有课、乙没课」也算成占用，结果偏小。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from .models import TimeSlot, Timetable, format_duration, format_time, weekday_name
from .slots import (
    DEFAULT_DAY_END,
    DEFAULT_DAY_START,
    DEFAULT_MERGE_GAP,
    daily_free_slots,
)

__all__ = [
    "CommonSlot",
    "intersect_slots",
    "common_free_slots",
    "render_common_slots",
]


@dataclass(frozen=True)
class CommonSlot:
    """一段「所有人都空着」的时间。"""

    weekday: int
    slot: TimeSlot

    @property
    def duration(self) -> int:
        """时长（分钟）。"""
        return self.slot.duration

    @property
    def start(self) -> int:
        return self.slot.start

    @property
    def end(self) -> int:
        return self.slot.end

    def __str__(self) -> str:
        return f"{weekday_name(self.weekday)} {self.slot}"


# --------------------------------------------------------------------------
# 区间交集
# --------------------------------------------------------------------------
def intersect_slots(left: Sequence[TimeSlot], right: Sequence[TimeSlot]) -> List[TimeSlot]:
    """两组**已排序且互不重叠**的时间段求交集（双指针，O(n+m)）。

    >>> from timetable.models import TimeSlot
    >>> a = [TimeSlot(480, 600), TimeSlot(660, 720)]
    >>> b = [TimeSlot(540, 700)]
    >>> [str(s) for s in intersect_slots(a, b)]
    ['09:00-10:00', '11:00-11:40']
    """
    result: List[TimeSlot] = []
    i = j = 0
    while i < len(left) and j < len(right):
        lo = max(left[i].start, right[j].start)
        hi = min(left[i].end, right[j].end)
        if lo < hi:
            result.append(TimeSlot(lo, hi))
        # 谁的尾巴更靠前，谁就往后挪一格
        if left[i].end <= right[j].end:
            i += 1
        else:
            j += 1
    return result


def _intersect_all(lists: Sequence[Sequence[TimeSlot]]) -> List[TimeSlot]:
    """多个列表的交集；任意一步空掉就提前收工。"""
    if not lists:
        return []
    result: List[TimeSlot] = list(lists[0])
    for other in lists[1:]:
        if not result:
            break
        result = intersect_slots(result, other)
    return result


# --------------------------------------------------------------------------
# 共同空闲
# --------------------------------------------------------------------------
def common_free_slots(
    timetables: Sequence[Timetable],
    day_start: int = DEFAULT_DAY_START,
    day_end: int = DEFAULT_DAY_END,
    merge: bool = True,
    max_gap: int = DEFAULT_MERGE_GAP,
    min_minutes: int = 0,
) -> List[CommonSlot]:
    """算出所有课表的共同空闲时段，**按长度降序**返回。

    :param timetables: 若干人的课表，至少一个。
    :param min_minutes: 过滤掉短于这个长度的结果，默认 0。
    """
    people = [t for t in timetables if t is not None]
    if not people:
        raise ValueError("至少需要一份课表才能算共同空闲时段")

    per_person: List[Dict[int, List[TimeSlot]]] = [
        daily_free_slots(
            table, day_start=day_start, day_end=day_end, merge=merge, max_gap=max_gap
        )
        for table in people
    ]

    result: List[CommonSlot] = []
    for weekday in range(7):
        shared = _intersect_all([person.get(weekday, []) for person in per_person])
        result.extend(CommonSlot(weekday, slot) for slot in shared)

    if min_minutes > 0:
        result = [item for item in result if item.duration >= min_minutes]

    # 越长越靠前；长度相同按星期、开始时间排，保证输出稳定
    return sorted(result, key=lambda item: (-item.duration, item.weekday, item.start))


# --------------------------------------------------------------------------
# 文本输出
# --------------------------------------------------------------------------
def render_common_slots(
    timetables: Sequence[Timetable],
    slots: Optional[Sequence[CommonSlot]] = None,
    day_start: int = DEFAULT_DAY_START,
    day_end: int = DEFAULT_DAY_END,
    top: Optional[int] = None,
) -> str:
    """把共同空闲时段渲染成「按长度降序」的榜单。"""
    people = [t for t in timetables if t is not None]
    if slots is None:
        slots = common_free_slots(people, day_start=day_start, day_end=day_end)

    names = "、".join((table.owner or f"同学{i + 1}") for i, table in enumerate(people))
    lines: List[str] = []
    lines.append(f"共同空闲时段 · {len(people)} 人（{names}）")
    lines.append(f"每日可用 {format_time(day_start)} - {format_time(day_end)}，按空闲时长降序")
    lines.append("=" * 56)

    if not slots:
        lines.append("")
        lines.append("很遗憾，这段时间里没有一个人人都有空的时段。")
        return "\n".join(lines)

    shown = list(slots[:top]) if top else list(slots)
    rank_width = len(str(len(shown)))
    for index, item in enumerate(shown, start=1):
        head = f"{index:>{rank_width}}. {item}"
        lines.append(f"  {head:<24}{format_duration(item.duration)}")

    lines.append("-" * 56)
    lines.append(f"共 {len(slots)} 段可共同安排的时间。")
    if top and len(slots) > top:
        lines.append(f"（只显示了最长的 {top} 段）")
    return "\n".join(lines)
