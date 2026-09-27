"""基础数据模型：时间、时间段、课程与课表。

设计约定
--------
* 星期用整数表示，``0 = 周一`` … ``6 = 周日``。
* 时间在内部统一用「从 00:00 起算的分钟数」（``int``）表示，
  只在输入 / 输出时转换成 ``"HH:MM"`` 字符串。
  这样比较、求长度、求交集都是纯整数运算，不会踩字符串排序的坑
  （例如 ``"9:00" > "10:00"`` 这种字典序陷阱）。
* ``Course`` / ``TimeSlot`` 都是 ``frozen`` 的，可安全地放进 ``set`` 或当字典键。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

__all__ = [
    "WEEKDAYS",
    "MINUTES_PER_DAY",
    "parse_weekday",
    "weekday_name",
    "parse_time",
    "format_time",
    "format_duration",
    "TimeSlot",
    "Course",
    "Timetable",
    "ensure_timetable",
    "gap_between",
    "merge_intervals",
]

#: 周一 ~ 周日的中文名，下标即 ``weekday`` 序号
WEEKDAYS: List[str] = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

#: 一天的分钟数，用于校验时间是否越界
MINUTES_PER_DAY = 24 * 60

# 星期几的各种写法。允许学生按自己习惯随便写，这里全部兜住。
_WEEKDAY_ALIASES: Dict[str, int] = {}


def _register_weekday(index: int, *names: str) -> None:
    for name in names:
        _WEEKDAY_ALIASES[name.lower()] = index


_register_weekday(0, "周一", "周1", "星期一", "星期1", "礼拜一", "一", "1", "mon", "monday")
_register_weekday(1, "周二", "周2", "星期二", "星期2", "礼拜二", "二", "2", "tue", "tues", "tuesday")
_register_weekday(2, "周三", "周3", "星期三", "星期3", "礼拜三", "三", "3", "wed", "wednesday")
_register_weekday(3, "周四", "周4", "星期四", "星期4", "礼拜四", "四", "4", "thu", "thur", "thursday")
_register_weekday(4, "周五", "周5", "星期五", "星期5", "礼拜五", "五", "5", "fri", "friday")
_register_weekday(5, "周六", "周6", "星期六", "星期6", "礼拜六", "六", "6", "sat", "saturday")
_register_weekday(6, "周日", "周天", "星期日", "星期天", "礼拜日", "礼拜天", "日", "天", "7", "sun", "sunday")

# "08:00" / "8：00"(全角) / "8.00" / "0800" / "800" / "8"
_TIME_RE = re.compile(r"^(\d{1,2})\s*[:：.．]\s*(\d{1,2})$")


def parse_weekday(text: object) -> int:
    """把各种写法的「星期几」转成 ``0~6`` 的整数。

    支持 ``周一`` / ``星期一`` / ``礼拜一`` / ``1`` / ``Mon`` / ``Monday`` 等。

    >>> parse_weekday("星期一")
    0
    >>> parse_weekday("SUN")
    6
    """
    key = str(text).strip().lower()
    if key in _WEEKDAY_ALIASES:
        return _WEEKDAY_ALIASES[key]
    # 兜一层 "星期10" 之类的脏数据：还认不出来就直接报错，别猜
    raise ValueError(f"无法识别的星期几：{text!r}（可写 周一~周日 / 1~7 / Mon~Sun）")


def weekday_name(weekday: int) -> str:
    """``0`` -> ``"周一"``。"""
    if not 0 <= weekday < 7:
        raise ValueError(f"星期几必须在 0~6 之间，收到 {weekday!r}")
    return WEEKDAYS[weekday]


def parse_time(text: object) -> int:
    """把 ``"HH:MM"`` 之类的时间写法转成「从 00:00 起的分钟数」。

    >>> parse_time("08:30")
    510
    >>> parse_time("8：05")   # 全角冒号也认
    485
    """
    raw = str(text).strip()
    # 先把 "08:00-12:00" 这类区间挡掉 —— parse_time 只接受单个时间点。
    # 否则 "-1:00" 会被当成 "100" 蒙混过关。
    if any(mark in raw for mark in ("-", "−", "–", "—", "~", "至")):
        raise ValueError(f"无法识别的时间：{text!r}（这里只接受单个时间点，如 08:00）")
    match = _TIME_RE.match(raw)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    else:
        # 兼容 "0800" / "800" / "8" 这类紧凑写法
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 4:
            hour, minute = int(digits[:2]), int(digits[2:])
        elif len(digits) == 3:
            hour, minute = int(digits[:1]), int(digits[1:])
        elif len(digits) in (1, 2):
            hour, minute = int(digits), 0
        else:
            raise ValueError(f"无法识别的时间：{text!r}（可写 08:00 / 8:00 / 0800）")

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"时间超出范围：{text!r}（小时 0~23，分钟 0~59）")
    return hour * 60 + minute


def format_time(minutes: int) -> str:
    """分钟数 -> ``"HH:MM"``。"""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def format_duration(minutes: int) -> str:
    """把时长转成人话，例如 ``135`` -> ``"2 小时 15 分"``。"""
    hours, rest = divmod(int(minutes), 60)
    if hours and rest:
        return f"{hours} 小时 {rest} 分"
    if hours:
        return f"{hours} 小时"
    return f"{rest} 分"


@dataclass(frozen=True, order=True)
class TimeSlot:
    """一个半开区间 ``[start, end)``，单位是分钟。

    之所以用半开区间：``09:00-10:00`` 和 ``10:00-11:00`` 应当视为**首尾相接**，
    而不是重叠。这样求空闲时段时不会凭空多出或漏掉一分钟。
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end > MINUTES_PER_DAY:
            raise ValueError(f"时间段必须在 00:00~24:00 之间：{self.start}~{self.end}")
        if self.start >= self.end:
            raise ValueError(
                f"开始时间必须早于结束时间：{format_time(self.start)}-{format_time(self.end)}"
            )

    # ---- 基本属性 ----------------------------------------------------
    @property
    def duration(self) -> int:
        """时长（分钟）。"""
        return self.end - self.start

    def __str__(self) -> str:
        return f"{format_time(self.start)}-{format_time(self.end)}"

    # ---- 区间运算 ----------------------------------------------------
    def overlaps(self, other: "TimeSlot") -> bool:
        """是否与另一时间段有重叠（相接不算重叠）。"""
        return self.start < other.end and other.start < self.end

    def touches(self, other: "TimeSlot", tolerance: int = 0) -> bool:
        """两段时间之间的空隙是否不超过 ``tolerance`` 分钟。"""
        return gap_between(self, other) <= tolerance

    def merge(self, other: "TimeSlot") -> "TimeSlot":
        """合并两段（取并集的外沿），可重叠也可相接。"""
        return TimeSlot(min(self.start, other.start), max(self.end, other.end))

    def slice(self, start: int, end: int) -> Optional["TimeSlot"]:
        """与 ``[start, end)`` 求交集，没有交集返回 ``None``。"""
        lo, hi = max(self.start, start), min(self.end, end)
        return TimeSlot(lo, hi) if lo < hi else None

    @classmethod
    def parse(cls, text: str) -> "TimeSlot":
        """解析 ``"08:00-12:00"`` 形式的字符串。"""
        parts = re.split(r"\s*[-~—至]\s*", str(text).strip())
        if len(parts) != 2:
            raise ValueError(f"无法识别的时间段：{text!r}（应形如 08:00-12:00）")
        return cls(parse_time(parts[0]), parse_time(parts[1]))


def gap_between(left: TimeSlot, right: TimeSlot) -> int:
    """两段时间之间的空隙（分钟）。重叠则为 0。"""
    if left.overlaps(right):
        return 0
    if left.end <= right.start:
        return right.start - left.end
    return left.start - right.end


def merge_intervals(slots: Iterable[TimeSlot], tolerance: int = 0) -> List[TimeSlot]:
    """把一堆区间按顺序合并；空隙不超过 ``tolerance`` 分钟的也合到一起。

    这是后面「求空闲时段」和「求共同空闲」共用的底层工具。

    >>> [str(s) for s in merge_intervals([TimeSlot(540, 585), TimeSlot(595, 640)])]
    ['09:00-09:45', '09:55-10:40']
    >>> [str(s) for s in merge_intervals([TimeSlot(540, 585), TimeSlot(595, 640)], 15)]
    ['09:00-10:40']
    """
    ordered = sorted(slots)
    merged: List[TimeSlot] = []
    for slot in ordered:
        if merged and gap_between(merged[-1], slot) <= tolerance:
            merged[-1] = merged[-1].merge(slot)
        else:
            merged.append(slot)
    return merged


@dataclass(frozen=True)
class Course:
    """一门课在某一星期几的一个上课时间段。

    「高等数学 周一 09:00-09:45」和「高等数学 周一 09:55-10:40」是**两条** ``Course``，
    它们要不要合并成一条，由 :mod:`timetable.slots` 决定，模型层保持原样。
    """

    name: str
    weekday: int
    start: int
    end: int
    location: str = ""

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValueError("课程名不能为空")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "location", str(self.location).strip())
        if not 0 <= self.weekday < 7:
            raise ValueError(f"星期几必须在 0~6 之间，收到 {self.weekday!r}")
        if not 0 <= self.start < self.end <= MINUTES_PER_DAY:
            raise ValueError(
                f"课程时间段非法：{format_time(self.start)}-{format_time(self.end)}"
            )

    @property
    def slot(self) -> TimeSlot:
        """该课占用的时间段。"""
        return TimeSlot(self.start, self.end)

    @property
    def duration(self) -> int:
        """时长（分钟）。"""
        return self.end - self.start

    def with_slot(self, slot: TimeSlot) -> "Course":
        """返回一门同名、同地点，但时间段替换为 ``slot`` 的课（合并时用）。"""
        return Course(self.name, self.weekday, slot.start, slot.end, self.location)

    def __str__(self) -> str:
        tail = f"  @{self.location}" if self.location else ""
        return f"{weekday_name(self.weekday)} {self.slot} {self.name}{tail}"


@dataclass
class Timetable:
    """一份课表 —— 属于某个人（``owner``）的一堆 ``Course``。"""

    owner: str = "我"
    courses: List[Course] = field(default_factory=list)

    # ---- 录入 --------------------------------------------------------
    def add(self, course: Course) -> Course:
        """直接塞一个 :class:`Course` 对象。"""
        if not isinstance(course, Course):
            raise TypeError(f"需要 Course 对象，收到 {type(course).__name__}")
        self.courses.append(course)
        return course

    def add_course(
        self,
        name: str,
        weekday: object,
        start: object,
        end: object,
        location: str = "",
    ) -> Course:
        """按「原始字符串」录入一门课，自动完成星期与时间的解析。

        这是给手动录入和 CSV 读取共用的入口，所以参数故意放宽成 ``object``：
        已经是 ``int`` 的值（例如手动录入时已经解析过的分钟数）会原样使用。

        注意两个「数字」的语义差别：字符串 ``"1"`` 表示**周一**，
        而整数 ``1`` 表示 ``weekday`` 序号，也就是**周二**。

        >>> tt = Timetable("张三")
        >>> tt.add_course("高等数学", "周一", "09:00", "10:40", "致理楼A302").duration
        100
        """
        weekday_value = weekday if isinstance(weekday, int) else parse_weekday(weekday)
        start_value = start if isinstance(start, int) else parse_time(start)
        end_value = end if isinstance(end, int) else parse_time(end)
        return self.add(
            Course(
                name=str(name),
                weekday=weekday_value,
                start=start_value,
                end=end_value,
                location=location,
            )
        )

    def extend(self, courses: Iterable[Course]) -> "Timetable":
        """批量追加，返回 ``self`` 方便链式调用。"""
        for course in courses:
            self.add(course)
        return self

    # ---- 查询 --------------------------------------------------------
    def courses_on(self, weekday: object) -> List[Course]:
        """取某天的课，**已按开始时间排好序**。"""
        index = parse_weekday(weekday) if not isinstance(weekday, int) else weekday
        return sorted(
            (c for c in self.courses if c.weekday == index),
            key=lambda c: (c.start, c.end, c.name),
        )

    def courses_by_day(self) -> Dict[int, List[Course]]:
        """``{0: [周一所有课], 1: [...], ...}``，七天都出现（没课的是空列表）。"""
        return {day: self.courses_on(day) for day in range(7)}

    @property
    def busy_days(self) -> List[int]:
        """有课的星期序号，升序。"""
        return sorted({c.weekday for c in self.courses})

    def __len__(self) -> int:
        return len(self.courses)

    def __iter__(self):
        return iter(self.courses)

    def __bool__(self) -> bool:
        return bool(self.courses)

    def __str__(self) -> str:
        return f"<Timetable {self.owner!r}: {len(self.courses)} 门次>"


def ensure_timetable(obj: object, owner: str = "我") -> Timetable:
    """把「课表或课程列表」统一成 :class:`Timetable`，方便对外部传参宽容一点。"""
    if isinstance(obj, Timetable):
        return obj
    if obj is None:
        return Timetable(owner)
    return Timetable(owner).extend(obj)  # type: ignore[arg-type]
