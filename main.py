#!/usr/bin/env python3
"""课表解析与空闲时段计算 —— 命令行入口。

用法示例::

    # 打印本周课表（标准 4 字段 CSV）
    python main.py show --csv data/student_a.csv

    # 教务系统导出的网格课表也能直接读
    python main.py show --csv data/raw_timetable_sample.csv --grid

    # 手动录入
    python main.py manual

    # 把教务导出的原始课表转成标准格式，方便二次编辑
    python main.py convert data/raw_timetable_sample.csv -o data/converted.csv
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

# 允许直接 `python main.py` 跑，也能 `python -m timetable` 跑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from timetable import (  # noqa: E402
    Timetable,
    load_csv,
    prompt_manual_timetable,
    render_timetable,
)
from timetable.raw_parser import deduplicate, parse_grid_text  # noqa: E402

DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "student_a.csv")


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
    parser.add_argument("--version", action="version", version="timetable 0.1.0")
    sub = parser.add_subparsers(dest="command", metavar="命令")

    # ---- show ----
    show = sub.add_parser("show", help="读入课表并打印「本周课表」文本视图")
    _add_source_args(show)
    show.add_argument(
        "--view",
        choices=["day", "grid"],
        default="day",
        help="展示方式：day = 按天列表（默认），grid = 周视图表格",
    )

    # ---- manual ----
    manual = sub.add_parser("manual", help="在终端里手动录入课表并打印")
    manual.add_argument("--owner", default="我", help="课表主人，默认「我」")
    manual.add_argument(
        "--view",
        choices=["day", "grid"],
        default="day",
        help="展示方式，默认 day",
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


def print_timetables(timetables, view: str = "day") -> None:
    for index, timetable in enumerate(timetables):
        if index:
            print()
        print(render_timetable(timetable, mode=view))


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------
def cmd_show(args) -> int:
    print_timetables(load_sources(args), view=args.view)
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
        "  python main.py show     --csv data/student_a.csv     打印本周课表\n"
        "  python main.py manual                                 手动录入课表\n"
        "  python main.py convert  data/raw_timetable_sample.csv 转换教务原始课表\n\n"
        "加 -h 看每个命令的详细用法：python main.py show -h"
    )
    return 0


COMMANDS = {
    "show": cmd_show,
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
