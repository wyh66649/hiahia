"""课表读入层：CSV 读取（两种格式自适应）+ 手动录入。

对外只需要记住三个函数：

``load_csv``
    读一个 CSV 文件，自动判断是「标准 4 字段格式」还是「教务系统导出的网格格式」。
``load_text``
    直接读一段 CSV 文本（写测试时很好用）。
``prompt_manual_timetable``
    在终端里一问一答地手动录入。

标准格式（表头顺序不限，列名大小写、中英文都兼容）::

    课程名,星期几,开始时间,结束时间,地点
    高等数学,周一,09:00,09:45,致理楼A302
    高等数学,周一,09:55,10:40,致理楼A302
"""

from __future__ import annotations

import csv
import io
import os
from typing import Dict, Iterable, List, Optional, Sequence

from .models import Course, Timetable, parse_time, parse_weekday
from .raw_parser import looks_like_grid, parse_grid_text

__all__ = [
    "TimetableFormatError",
    "STANDARD_FIELDS",
    "read_text_file",
    "load_text",
    "load_csv",
    "load_many",
    "owner_from_filename",
    "prompt_manual_timetable",
]

#: 标准格式必须的四个字段
STANDARD_FIELDS = ("课程名", "星期几", "开始时间", "结束时间")

#: 列名的各种别名 —— 学生自己写的 CSV 表头千奇百怪，这里尽量兜住
_FIELD_ALIASES: Dict[str, set] = {
    "课程名": {"课程名", "课程", "课程名称", "课名", "科目", "name", "course", "course_name", "subject"},
    "星期几": {"星期几", "星期", "周几", "上课星期", "day", "weekday", "week", "week_day"},
    "开始时间": {"开始时间", "开始", "起始时间", "上课时间", "start", "start_time", "begin", "从"},
    "结束时间": {"结束时间", "结束", "终止时间", "下课时间", "end", "end_time", "finish", "到"},
    "地点": {"地点", "教室", "上课地点", "上课教室", "位置", "location", "room", "classroom", "place"},
}

#: 猜文件编码的顺序。教务系统导出的 CSV 大多是 GBK，先试 UTF-8 系列不会误伤。
_ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5")


class TimetableFormatError(ValueError):
    """课表文件格式不对。错误信息里会带上行号，方便直接改。"""


# --------------------------------------------------------------------------
# 编码 / 文件
# --------------------------------------------------------------------------
def read_text_file(path: str, encoding: Optional[str] = None) -> str:
    """读文本文件；不给编码时逐个试，直到能解码为止。

    教务系统导出的课表通常是 GBK，而手写 CSV 一般是 UTF-8，
    所以这里不强制用户传编码。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到课表文件：{path}")

    if encoding:
        with open(path, "r", encoding=encoding, newline="") as handle:
            return handle.read()

    last_error: Optional[Exception] = None
    for candidate in _ENCODING_CANDIDATES:
        try:
            with open(path, "r", encoding=candidate, newline="") as handle:
                return handle.read()
        except (UnicodeDecodeError, LookupError) as error:  # noqa: PERF203
            last_error = error
    raise TimetableFormatError(f"读不出 {path} 的内容，可能不是文本文件（{last_error}）")


# --------------------------------------------------------------------------
# 标准 4 字段格式
# --------------------------------------------------------------------------
def _normalise_header(name: str) -> Optional[str]:
    """把表头单元格映射成标准字段名，认不出来返回 ``None``。"""
    key = str(name).strip().lower().replace(" ", "").replace("_", "")
    for standard, aliases in _FIELD_ALIASES.items():
        if key in {a.lower().replace(" ", "").replace("_", "") for a in aliases}:
            return standard
    return None


def _build_column_map(header: Sequence[str]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for index, cell in enumerate(header):
        field = _normalise_header(cell)
        if field and field not in mapping:
            mapping[field] = index
    return mapping


def load_text(text: str, owner: Optional[str] = None, strict: bool = False) -> Timetable:
    """从 CSV 文本读课表，自动判断格式。

    :param owner: 课表主人。网格格式下留空会自动取课表里印着的姓名。
    :param strict: 为 ``True`` 时，任何一行出错都直接抛异常；
        ``False``（默认）则跳过坏行，把问题收集起来打印提示，尽量把能读的读进来。
    """
    if looks_like_grid(text):
        parsed = parse_grid_text(text)
        timetable = Timetable(owner=owner or parsed.owner or "我")
        timetable.extend(parsed.courses())
        return timetable

    return _parse_standard_text(text, owner=owner or "我", strict=strict)


def _parse_standard_text(text: str, owner: str = "我", strict: bool = False) -> Timetable:
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        raise TimetableFormatError("课表内容为空")

    # ---- 表头 ----
    header = rows[0]
    columns = _build_column_map(header)
    body = rows[1:]

    missing = [f for f in STANDARD_FIELDS if f not in columns]
    if missing:
        # 没有可识别的表头时，退化成「按固定列序」解析（课程名,星期几,开始,结束[,地点]）
        if len(header) >= 4 and _normalise_header(header[0]) is None:
            columns = {name: index for index, name in enumerate(STANDARD_FIELDS)}
            if len(header) >= 5:
                columns["地点"] = 4
            body = rows
            missing = []
        else:
            raise TimetableFormatError(
                "CSV 表头缺少字段："
                + "、".join(missing)
                + f"\n实际表头：{','.join(header)}"
                + f"\n需要的字段：{','.join(STANDARD_FIELDS)}（地点可选）"
            )

    # ---- 逐行 ----
    timetable = Timetable(owner=owner)
    problems: List[str] = []
    for line_number, row in enumerate(body, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if row[0].lstrip().startswith("#"):  # 支持用 # 写注释
            continue

        def cell(field: str) -> str:
            index = columns.get(field, -1)
            return row[index].strip() if 0 <= index < len(row) else ""

        try:
            if not cell("课程名"):
                raise ValueError("课程名为空")
            timetable.add_course(
                name=cell("课程名"),
                weekday=cell("星期几"),
                start=cell("开始时间"),
                end=cell("结束时间"),
                location=cell("地点"),
            )
        except (ValueError, TypeError) as error:
            message = f"第 {line_number} 行：{error}（原始内容：{','.join(row)}）"
            if strict:
                raise TimetableFormatError(message) from error
            problems.append(message)

    if problems:
        print(f"⚠️  有 {len(problems)} 行没能读进来，已跳过：")
        for problem in problems:
            print(f"   - {problem}")

    if not timetable.courses:
        raise TimetableFormatError("一行课都没读进来，请检查文件内容和表头")

    return timetable


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------
def load_csv(path: str, owner: Optional[str] = None, encoding: Optional[str] = None, strict: bool = False) -> Timetable:
    """读一个课表 CSV 文件。

    名字的优先级：**显式传入的 owner > 课表里印着的姓名 > 文件名**。
    文件名会顺手去掉 ``课表`` / ``课程表`` / ``_raw`` 这类后缀，
    ``data/张三课表.csv`` 就会显示成「张三」。
    """
    text = read_text_file(path, encoding=encoding)
    file_owner = owner_from_filename(path)

    if looks_like_grid(text):
        parsed = parse_grid_text(text)
        return Timetable(owner=owner or parsed.owner or file_owner).extend(parsed.courses())

    return _parse_standard_text(text, owner=owner or file_owner, strict=strict)


#: 从文件名推名字时要剥掉的尾巴
_OWNER_SUFFIXES = ("课程表", "课表", "timetable", "_raw", "-raw", "_课表")


def owner_from_filename(path: str) -> str:
    """``data/张三课表.csv`` -> ``张三``；去掉常见后缀，认不出就原样返回。"""
    stem = os.path.splitext(os.path.basename(path))[0].strip() or "我"
    lowered = stem.lower()
    for suffix in _OWNER_SUFFIXES:
        if lowered.endswith(suffix.lower()) and len(stem) > len(suffix):
            stem = stem[: -len(suffix)]
            break
    # 顺手把 "_timetable" 留下的下划线、连字符之类也去掉
    cleaned = stem.strip().strip("_-— ").strip()
    return cleaned or stem.strip() or "我"


def load_many(paths: Iterable[str], **kwargs) -> List[Timetable]:
    """一次读多份课表，顺序与传入一致。"""
    return [load_csv(path, **kwargs) for path in paths]


# --------------------------------------------------------------------------
# 手动录入
# --------------------------------------------------------------------------
def prompt_manual_timetable(owner: str = "我", input_func=input, output_func=print) -> Timetable:
    """在终端里问答式录入课表。

    课程名直接回车即结束录入。为了能在测试里跑，``input_func`` / ``output_func`` 都可注入。

    >>> answers = iter(["高等数学", "周一", "09:00", "10:40", ""])
    >>> tt = prompt_manual_timetable(output_func=lambda *a: None, input_func=lambda prompt="": next(answers))
    >>> len(tt)
    1
    """
    timetable = Timetable(owner=owner)
    output_func("")
    output_func("=" * 46)
    output_func("  手动录入课表（课程名直接回车 = 结束）")
    output_func("  星期几可写：周一~周日 / 1~7 / Mon~Sun")
    output_func("  时间可写：09:00 / 9:00 / 0900")
    output_func("=" * 46)

    while True:
        try:
            name = input_func("课程名（回车结束）：").strip()
        except (EOFError, KeyboardInterrupt):
            output_func("")
            break
        if not name:
            break

        # 星期几 / 时间反复追问，直到填对为止
        weekday = _ask_until_ok(input_func, output_func, "星期几：", parse_weekday)
        start = _ask_until_ok(input_func, output_func, "开始时间：", parse_time)
        end = _ask_until_ok(input_func, output_func, "结束时间：", parse_time, lower_bound=start)
        location = input_func("地点（可留空）：").strip()

        try:
            course = timetable.add_course(name, weekday, start, end, location)
        except ValueError as error:
            output_func(f"✗ {error}，这条先不算，继续下一条。")
            continue
        output_func(f"✓ 已加入：{course}")
    output_func("")
    output_func(f"录入完成，共 {len(timetable)} 门次。")
    return timetable


def _ask_until_ok(input_func, output_func, prompt: str, parser, lower_bound: Optional[int] = None):
    """反复追问，直到解析成功为止。"""
    while True:
        raw = input_func(prompt)
        try:
            value = parser(raw)
        except (ValueError, TypeError) as error:
            output_func(f"  ✗ {error}")
            continue
        if lower_bound is not None and value <= lower_bound:
            output_func(f"  ✗ 结束时间要晚于开始时间 {lower_bound // 60:02d}:{lower_bound % 60:02d}")
            continue
        return value
