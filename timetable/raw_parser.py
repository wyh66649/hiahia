"""教务系统导出的「原始课表」解析器。

教务系统导出的 CSV 是一张**网格表**：第一列是节次，后面每一列是一天，
单元格里塞的是这门课的信息，形如::

    节次/星期,星期一,星期二,...
    第一单节08:00-08:45,,大学生心理健康教育 05
    (08:00-08:45),,9周 毛老师 08:00-10:30 【3-227】,...
    第二双节第1小节09:00-09:45,"工科数学分析Ⅰ 07
    (09:00-09:45)","1-4周,6-18周 程老师 09:00-10:30 【1-210】",,...

一个单元格里最常见的是「1 行课程名 + N 行明细」，N 行明细对应不同周次，
要并成一条课；也可能堆着完全不同的课，那就要拆开。
真正的上课时间以单元格里的时间为准，节次标签只当兜底。

解析结果统一成 :class:`~timetable.models.Course`，
额外的 ``weeks`` / ``teacher`` 通过 :class:`RawCourse` 带出来，方便原样导出。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .models import Course, TimeSlot, parse_time, parse_weekday

__all__ = [
    "RawCourse",
    "RawTimetable",
    "looks_like_grid",
    "parse_cell",
    "parse_grid_text",
    "deduplicate",
]

# 单元格里出现的 "09:00-10:30"
_TIME_RANGE_RE = re.compile(r"(\d{1,2}[:：]\d{2})\s*[-~—－至]\s*(\d{1,2}[:：]\d{2})")
# 【3-227】 / 【E-201（原2A-201）】 / [1-210]
_ROOM_RE = re.compile(r"[【\[]([^】\]]+)[】\]]")
# "1-4周,6-18周" / "9周" / "1-4周、6-18周"
_WEEKS_RE = re.compile(r"\d[\d\s,\-、]*周(?:\s*[,，、]\s*\d[\d\s\-]*周)*")
# 课程名后面的课程编号，例如 "工科数学分析Ⅰ 07"
_COURSE_CODE_RE = re.compile(r"\s+\d{1,3}$")
# 表头里出现这些词，说明大概率是网格格式（注意：标准表头里的「星期几」不算）
_GRID_HEADER_HINTS = ("节次", "周次")
# 页脚噪声
_FOOTER_HINTS = ("打印人", "打印时间", "制表人")
_META_RE = re.compile(r"([\u4e00-\u9fa5]{2,4})\s*\[(\d{6,})\]")
_SEASON_RE = re.compile(
    r"(\d{4}\s*[-−–—]\s*\d{4}\s*学年\s*第[一二三四五六七八九十\d]{1,3}学期)"
)


@dataclass
class RawCourse:
    """原始课表里的一条记录（比 :class:`Course` 多带周次、教师）。"""

    course: Course
    teacher: str = ""
    weeks: str = ""
    raw_name: str = ""
    period_label: str = ""

    def to_row(self) -> List[str]:
        """导出成标准 5 字段 CSV 的一行。"""
        return [
            self.course.name,
            f"周{['一', '二', '三', '四', '五', '六', '日'][self.course.weekday]}",
            f"{self.course.start // 60:02d}:{self.course.start % 60:02d}",
            f"{self.course.end // 60:02d}:{self.course.end % 60:02d}",
            self.course.location,
        ]


@dataclass
class RawTimetable:
    """整份原始课表的解析结果。"""

    owner: str = ""
    student_id: str = ""
    term: str = ""
    records: List[RawCourse] = field(default_factory=list)

    def courses(self) -> List[Course]:
        return [record.course for record in self.records]


# --------------------------------------------------------------------------
# 格式嗅探
# --------------------------------------------------------------------------
def _first_cells(lines: Sequence[str], limit: int = 6) -> List[List[str]]:
    rows: List[List[str]] = []
    for line in lines:
        if not line.strip():
            continue
        rows.append(next(csv.reader(io.StringIO(line))))
        if len(rows) >= limit:
            break
    return rows


def _count_weekday_cells(row: Sequence[str]) -> int:
    """数一数这行里有多少格能被识别成「星期几」。"""
    count = 0
    for cell in row[1:]:
        text = cell.strip()
        if not text:
            continue
        try:
            parse_weekday(text)
        except ValueError:
            continue
        count += 1
    return count


def _is_grid_header(row: Sequence[str]) -> bool:
    """判断一行是不是网格课表的表头。

    只看「星期」这类关键词**不够** ——
    ``课程名,星期几,开始时间,结束时间`` 这种标准表头也带「星期」二字，会误判。
    所以要求：至少 3 列真的是星期几，或者首列明确写着「节次 / 周次」。
    """
    if len(row) < 3:
        return False
    if _count_weekday_cells(row) >= 3:
        return True
    first = row[0].strip()
    return any(hint in first for hint in _GRID_HEADER_HINTS) and _count_weekday_cells(row) >= 1


def looks_like_grid(text: str) -> bool:
    """判断一段 CSV 文本是不是教务系统导出的网格课表。"""
    return any(_is_grid_header(row) for row in _first_cells(text.splitlines()))


# --------------------------------------------------------------------------
# 单元格解析
# --------------------------------------------------------------------------
def _is_detail_line(line: str) -> bool:
    """判断一行是不是「课程明细行」（含周次 / 时间 / 教室）。

    课程名行形如 ``工科数学分析Ⅰ 07``；明细行形如
    ``1-4周,6-18周 程老师 09:00-10:30 【1-210】``。
    """
    return bool(
        _TIME_RANGE_RE.search(line) or _ROOM_RE.search(line) or _WEEKS_RE.search(line)
    )


def _split_entries(cell: str) -> List[List[str]]:
    """把单元格按「课程名行 + 若干明细行」切成若干组。"""
    lines = [line.strip() for line in cell.splitlines() if line.strip()]
    groups: List[List[str]] = []
    for line in lines:
        if groups and _is_detail_line(line):
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def _dedup_keep_order(values: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(v for v in values if v))


def _extract_detail(block: List[str]) -> Tuple[Optional[TimeSlot], str, str, str]:
    """从一组行里抽出 (时间段, 周次, 教师, 教室)。

    同一门课的不同周次常常写成多行（``3周 王老师 …`` / ``6周 李老师 …``），
    这里并成一条：时间取并集，周次用 ``、`` 拼、教师用 ``/`` 拼。
    """
    detail_lines = block[1:]
    if not detail_lines:
        return None, "", "", ""

    starts: List[int] = []
    ends: List[int] = []
    weeks_list: List[str] = []
    rooms: List[str] = []
    teachers: List[str] = []

    for line in detail_lines:
        time_match = _TIME_RANGE_RE.search(line)
        if time_match:
            starts.append(parse_time(time_match.group(1)))
            ends.append(parse_time(time_match.group(2)))

        room_match = _ROOM_RE.search(line)
        if room_match:
            rooms.append(room_match.group(1).strip())

        weeks_match = _WEEKS_RE.search(line)
        if weeks_match:
            weeks_list.append(re.sub(r"\s+", "", weeks_match.group(0)))

        # 依次抠掉周次 / 时间 / 教室，剩下的基本就是教师名
        residue = line
        for match in (weeks_match, time_match, room_match):
            if match:
                residue = residue.replace(match.group(0), " ", 1)
        residue = re.sub(r"\s+", " ", residue).strip(" ,，、")
        if residue:
            teachers.append(residue)

    slot = TimeSlot(min(starts), max(ends)) if starts and ends else None
    return (
        slot,
        "、".join(_dedup_keep_order(weeks_list)),
        "/".join(_dedup_keep_order(teachers)),
        rooms[0] if rooms else "",
    )


def parse_cell(cell: str, weekday: int, period_label: str = "") -> List[RawCourse]:
    """解析一个单元格，可能拆出多门课。"""
    if not cell or not cell.strip():
        return []

    # 单元格里没有时间时，退回用节次标签的时间
    fallback: Optional[TimeSlot] = None
    label_match = _TIME_RANGE_RE.search(period_label)
    if label_match:
        fallback = TimeSlot(
            parse_time(label_match.group(1)), parse_time(label_match.group(2))
        )

    results: List[RawCourse] = []
    for block in _split_entries(cell):
        raw_name = block[0].strip()
        name = _COURSE_CODE_RE.sub("", raw_name).strip()
        if not name:
            continue

        slot, weeks, teacher, room = _extract_detail(block)
        if slot is None:
            slot = fallback
        if slot is None:
            # 一点时间信息都没有就跳过，别猜一个出来误导人
            continue

        results.append(
            RawCourse(
                course=Course(
                    name=name,
                    weekday=weekday,
                    start=slot.start,
                    end=slot.end,
                    location=room,
                ),
                teacher=teacher,
                weeks=weeks,
                raw_name=raw_name,
                period_label=period_label,
            )
        )
    return results


# --------------------------------------------------------------------------
# 整表解析
# --------------------------------------------------------------------------
def parse_grid_text(text: str) -> RawTimetable:
    """解析整份网格课表文本。"""
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("课表内容为空")

    result = RawTimetable()

    # ---- 找到表头行，顺便从标题行里扒出姓名 / 学号 / 学年学期 ----
    header_index = -1
    for index, row in enumerate(rows[:6]):
        if _is_grid_header(row):
            header_index = index
            break
    if header_index < 0:
        raise ValueError("没找到表头行（应含「节次/星期」和 星期一 ~ 星期日 各列）")

    for row in rows[:header_index]:
        joined = ",".join(row)
        meta = _META_RE.search(joined)
        if meta:
            result.owner, result.student_id = meta.group(1), meta.group(2)
        season = _SEASON_RE.search(joined)
        if season:
            result.term = season.group(1).strip()

    header = rows[header_index]
    # 首列是节次标签，其余列按星期解析；认不出星期几的列直接跳过
    day_columns: List[Tuple[int, int]] = []
    for column in range(1, len(header)):
        label = header[column].strip()
        if not label:
            continue
        try:
            day_columns.append((column, parse_weekday(label)))
        except ValueError:
            continue
    if not day_columns:
        raise ValueError("表头里没有识别出任何星期列")

    # ---- 逐行取数据 ----
    for row in rows[header_index + 1 :]:
        label = row[0].strip() if row else ""
        has_time = any(_TIME_RANGE_RE.search(cell) for cell in row[1:])
        if any(hint in ",".join(row) for hint in _FOOTER_HINTS) and not has_time:
            break
        for column, weekday in day_columns:
            if column >= len(row):
                continue
            result.records.extend(parse_cell(row[column], weekday, label))

    if not result.records:
        raise ValueError("表头认出来了，但一节课都没解析到，请检查文件是否完整")
    return result


def deduplicate(records: Sequence[RawCourse]) -> List[RawCourse]:
    """去掉完全重复的记录，并按「星期 + 开始时间 + 课程名」排序。"""
    seen: Dict[Tuple, RawCourse] = {}
    for record in records:
        key = (
            record.course.name,
            record.course.weekday,
            record.course.start,
            record.course.end,
        )
        if key not in seen:
            seen[key] = record
    return sorted(seen.values(), key=lambda r: (r.course.weekday, r.course.start, r.course.name))
