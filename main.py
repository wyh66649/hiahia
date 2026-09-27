#!/usr/bin/env python3
"""课表解析与空闲时段计算 —— 命令行入口。

用法示例::

    # 打印本周课表（标准 4 字段 CSV）
    python main.py show --csv data/student_a.csv

    # 教务系统导出的网格课表也能直接读
    python main.py show --csv data/raw_timetable_sample.csv --view grid

    # 算空闲时段（每日可用 08:00-22:00）
    python main.py free --csv data/student_a.csv --day-start 08:00 --day-end 22:00

    # 找两个人的共同空闲时段（按长度降序）
    python main.py common --csv data/student_a.csv --csv data/student_b.csv

    # 手动录入
    python main.py manual

    # 把教务导出的原始课表转成标准格式，方便二次编辑
    python main.py convert data/raw_timetable_sample.csv -o data/converted.csv
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Tuple

# 允许直接 `python main.py` 跑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from timetable import (  # noqa: E402
    DEFAULT_MERGE_GAP,
    Timetable,
    common_free_slots,
    daily_free_slots,
    load_csv,
    merged_courses_by_day,
    parse_time,
    parse_weekday,
    prompt_manual_timetable,
    render_common_slots,
    render_free_slots,
    render_timetable,
    weekday_name,
)
from timetable.raw_parser import deduplicate, parse_grid_text  # noqa: E402

__version__ = "0.3.0"

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(ROOT, "data", "student_a.csv")


# --------------------------------------------------------------------------
# 参数
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="课表解析与空闲时段计算小工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"timetable {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="命令")

    # ---- show ----
    show = sub.add_parser("show", help="读入课表并打印「本周课表」文本视图")
    _add_source_args(show)
    _add_merge_args(show)
    show.add_argument(
        "--view",
        choices=["day", "grid"],
        default="day",
        help="展示方式：day = 按天列表（默认），grid = 周视图表格",
    )

    # ---- free ----
    free = sub.add_parser("free", help="算出每天的可用空闲时段")
    _add_source_args(free)
    _add_merge_args(free)
    free.add_argument("--day-start", default="08:00", help="每天可用的开始时间，默认 08:00")
    free.add_argument("--day-end", default="22:00", help="每天可用的结束时间，默认 22:00")
    free.add_argument(
        "--min-minutes",
        type=int,
        default=0,
        metavar="分钟",
        help="只显示不短于这个长度的空闲时段，默认 0（全部保留）",
    )
    free.add_argument("--day", default=None, metavar="星期", help="只看某一天，例如 --day 周三")

    # ---- common ----
    common = sub.add_parser("common", help="算出多个人的共同空闲时段（按空闲时长降序）")
    _add_source_args(common)
    _add_merge_args(common)
    common.add_argument("--day-start", default="08:00", help="每天可用的开始时间，默认 08:00")
    common.add_argument("--day-end", default="22:00", help="每天可用的结束时间，默认 22:00")
    common.add_argument(
        "--min-minutes",
        type=int,
        default=0,
        metavar="分钟",
        help="只显示不短于这个长度的空闲时段，默认 0",
    )
    common.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="只显示最长的前 N 段，默认全部显示",
    )

    # ---- manual ----
    manual = sub.add_parser("manual", help="在终端里手动录入课表并打印")
    manual.add_argument("--owner", default="我", help="课表主人，默认「我」")
    manual.add_argument(
        "--view", choices=["day", "grid"], default="day", help="展示方式，默认 day"
    )

    # ---- convert ----
    convert = sub.add_parser("convert", help="把教务导出的原始课表转成标准 4 字段 CSV")
    convert.add_argument("path", help="原始课表 CSV 路径")
    convert.add_argument("-o", "--output", default=None, help="输出路径，默认打印到屏幕")
    convert.add_argument("--with-meta", action="store_true", help="额外导出教师 / 周次两列")

    return parser


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    """给需要「读课表」的子命令挂上公共参数。"""
    parser.add_argument(
        "--csv",
        action="append",
        default=None,
        metavar="文件",
        help="课表 CSV 路径，可重复写多个；不写则默认读 data/student_a.csv",
    )
    parser.add_argument("--owner", default=None, help="课表主人名字，默认取文件名")
    parser.add_argument("--encoding", default=None, help="强制指定文件编码（默认自动识别）")


def _add_merge_args(parser: argparse.ArgumentParser) -> None:
    """合并连续节次相关的参数（需求 2）。"""
    parser.add_argument(
        "--merge",
        dest="merge",
        action="store_true",
        default=True,
        help="合并同一课程的连续节次（默认开启）",
    )
    parser.add_argument(
        "--no-merge",
        dest="merge",
        action="store_false",
        help="不合并，保留每一节，能直观对比出碎片的效果",
    )
    parser.add_argument(
        "--gap",
        type=int,
        default=DEFAULT_MERGE_GAP,
        metavar="分钟",
        help=f"两节之间不超过多少分钟算连续，默认 {DEFAULT_MERGE_GAP}",
    )


# --------------------------------------------------------------------------
# 公共工具
# --------------------------------------------------------------------------
def load_sources(args) -> List[Timetable]:
    """按参数读入一份或多份课表。"""
    paths = args.csv or [DEFAULT_CSV]
    timetables: List[Timetable] = []

    for path in paths:
        if not os.path.exists(path):
            raise SystemExit(f"✗ 找不到文件：{path}")
        timetables.append(load_csv(path, owner=args.owner, encoding=args.encoding))
    return timetables


def print_timetables(
    timetables: List[Timetable],
    view: str = "day",
    merge: bool = True,
    gap: int = DEFAULT_MERGE_GAP,
) -> None:
    for index, timetable in enumerate(timetables):
        if index:
            print()
        by_day = merged_courses_by_day(timetable, max_gap=gap) if merge else None
        print(render_timetable(timetable, mode=view, courses_by_day=by_day))


def parse_day_range(args) -> Tuple[int, int]:
    """把 ``--day-start`` / ``--day-end`` 解析成分钟数。"""
    start = parse_time(args.day_start)
    end = parse_time(args.day_end)
    if start >= end:
        raise SystemExit(f"✗ 可用时间范围非法：{args.day_start}-{args.day_end}")
    return start, end


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------
def cmd_show(args) -> int:
    print_timetables(load_sources(args), view=args.view, merge=args.merge, gap=args.gap)
    return 0


def cmd_free(args) -> int:
    day_start, day_end = parse_day_range(args)
    timetables = load_sources(args)

    only_day: Optional[int] = None
    if args.day:
        try:
            only_day = parse_weekday(args.day)
        except ValueError as error:
            raise SystemExit(f"✗ {error}")

    for index, timetable in enumerate(timetables):
        if index:
            print()
        free_by_day = daily_free_slots(
            timetable,
            day_start=day_start,
            day_end=day_end,
            merge=args.merge,
            max_gap=args.gap,
            min_minutes=args.min_minutes,
        )
        if only_day is not None:
            print(f"（只看 {weekday_name(only_day)}）")
            free_by_day = {only_day: free_by_day[only_day]}
        print(
            render_free_slots(
                timetable,
                free_by_day=free_by_day,
                day_start=day_start,
                day_end=day_end,
                show_empty=only_day is None,
            )
        )
    return 0


def cmd_common(args) -> int:
    day_start, day_end = parse_day_range(args)
    timetables = load_sources(args)

    if len(timetables) < 2:
        print("提示：只给了 1 份课表，结果和它的个人空闲时段是一样的。")
        print()

    slots = common_free_slots(
        timetables,
        day_start=day_start,
        day_end=day_end,
        merge=args.merge,
        max_gap=args.gap,
        min_minutes=args.min_minutes,
    )
    print(
        render_common_slots(
            timetables,
            slots=slots,
            day_start=day_start,
            day_end=day_end,
            top=args.top,
        )
    )
    return 0


def cmd_manual(args) -> int:
    timetable = prompt_manual_timetable(owner=args.owner)
    if not timetable.courses:
        print("没有录入任何课程。")
        return 0
    print()
    print(render_timetable(timetable, mode=args.view))
    return 0


def cmd_convert(args) -> int:
    from timetable import read_text_file

    text = read_text_file(args.path)
    parsed = parse_grid_text(text)
    records = deduplicate(parsed.records)

    lines = ["课程名,星期几,开始时间,结束时间,地点"]
    if args.with_meta:
        lines[0] += ",教师,周次"
    for record in records:
        row = record.to_row()
        if args.with_meta:
            row += [record.teacher, record.weeks]
        lines.append(",".join(row))
    output = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as handle:
            handle.write(output + "\n")
        print(f"✓ 已写出 {len(records)} 条课程 -> {args.output}")
    else:
        print(output)
    return 0


def cmd_menu() -> int:
    """没给子命令时，打印一份简短的上手指引。"""
    print(
        "课表解析与空闲时段计算小工具\n\n"
        "  python main.py show   --csv data/student_a.csv                打印本周课表\n"
        "  python main.py free   --csv data/student_a.csv                算空闲时段\n"
        "  python main.py common --csv data/student_a.csv \\\n"
        "                        --csv data/student_b.csv                找共同空闲\n"
        "  python main.py manual                                          手动录入课表\n"
        "  python main.py convert data/raw_timetable_sample.csv           转换教务原始课表\n\n"
        "加 -h 看每个命令的详细用法：python main.py common -h"
    )
    return 0


COMMANDS = {
    "show": cmd_show,
    "free": cmd_free,
    "common": cmd_common,
    "manual": cmd_manual,
    "convert": cmd_convert,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        return cmd_menu()
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
