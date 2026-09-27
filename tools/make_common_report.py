#!/usr/bin/env python3
"""生成「共同空闲时段」报告 -> docs/共同空闲时段.md。

三个人（或两个、多个）的课表放一起跑一遍需求 3，把结果落成 markdown，
方便直接贴进文档 / 交作业 / 发群里。

用法::

    python tools/make_common_report.py
    python tools/make_common_report.py --csv data/同学A课表.csv --csv data/同学B课表.csv
    python tools/make_common_report.py --day-start 08:00 --day-end 22:00 --min-minutes 60

默认读取仓库里那两份真实（已脱敏）的教务导出台账。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from timetable import (  # noqa: E402
    CommonSlot,
    Timetable,
    common_free_slots,
    format_duration,
    format_time,
    load_csv,
    parse_time,
    weekday_name,
)

DEFAULT_CSVS = [
    os.path.join(ROOT, "data", "同学A课表.csv"),
    os.path.join(ROOT, "data", "同学B课表.csv"),
]
DEFAULT_OUTPUT = os.path.join(ROOT, "docs", "共同空闲时段.md")


def load_people(paths: Sequence[str]) -> List[Timetable]:
    return [load_csv(path) for path in paths]


def render_day_table(people: Sequence[Timetable]) -> List[str]:
    """两人的「每周对照表」：每天各自上了哪些课。"""
    lines = ["| 星期 | " + " | ".join(t.owner or f"同学{i + 1}" for i, t in enumerate(people)) + " |"]
    lines.append("| --- |" + " --- |" * len(people))

    for weekday in range(7):
        cells = []
        for table in people:
            courses = table.courses_on(weekday)
            if not courses:
                cells.append("—")
            else:
                cells.append("<br>".join(f"{c.slot} {c.name}" for c in courses))
        lines.append(f"| {weekday_name(weekday)} | " + " | ".join(cells) + " |")
    return lines


def render_ranking(slots: Sequence[CommonSlot]) -> List[str]:
    lines = ["| # | 时段 | 时长 |", "| --- | --- | --- |"]
    for index, item in enumerate(slots, start=1):
        lines.append(f"| {index} | {weekday_name(item.weekday)} {item.slot} | {format_duration(item.duration)} |")
    return lines


def build_report(
    people: Sequence[Timetable],
    day_start: int,
    day_end: int,
    min_minutes: int,
    source_names: Sequence[str],
) -> str:
    all_slots = common_free_slots(people, day_start=day_start, day_end=day_end)
    useful = [s for s in all_slots if s.duration >= min_minutes]

    days = sorted({slot.weekday for slot in all_slots})
    total_minutes = sum(slot.duration for slot in all_slots)
    names = "、".join(t.owner or f"同学{i + 1}" for i, t in enumerate(people))

    lines: List[str] = []
    lines.append(f"# 需求 3 实例：{names} 的共同空闲时段")
    lines.append("")
    lines.append(
        "> 本文件由 `tools/make_common_report.py` 自动生成，"
        "改完课表重跑一下就能刷新。"
    )
    lines.append("")
    lines.append("## 输入")
    lines.append("")
    lines.append("| 课表主人 | 来源文件 | 一周课次 | 有课天数 |")
    lines.append("| --- | --- | --- | --- |")
    for table, source in zip(people, source_names):
        rel = os.path.relpath(source, ROOT).replace(os.sep, "/")
        lines.append(
            f"| {table.owner} | `{rel}` | {len(table)} | {len(table.busy_days)} |"
        )
    lines.append("")
    lines.append(f"- 每日可用时间范围：**{format_time(day_start)} - {format_time(day_end)}**")
    lines.append("- 排序规则：**空闲时长降序**，长度相同按星期、开始时间排")
    lines.append("")
    lines.append("## 每周课表对照")
    lines.append("")
    lines.extend(render_day_table(people))
    lines.append("")

    if not all_slots:
        lines.append("## 结果")
        lines.append("")
        lines.append("这段时间里没有一个人人都有空的时段。")
        return "\n".join(lines) + "\n"

    lines.append(f"## 共同空闲时段（共 {len(all_slots)} 段）")
    lines.append("")
    lines.append(
        f"按空闲时长降序排列，合计 {format_duration(total_minutes)}，"
        f"分布在 {'、'.join(weekday_name(d) for d in days)}。"
    )
    lines.append("")
    lines.extend(render_ranking(all_slots))
    lines.append("")

    longest = all_slots[0]
    lines.append("### 结论")
    lines.append("")
    lines.append(
        f"- 最长的一段是 **{weekday_name(longest.weekday)} {longest.slot}**，"
        f"足足 {format_duration(longest.duration)}。"
    )
    lines.append(
        f"- 排前 5 的时段依次是："
        + "、".join(f"{weekday_name(s.weekday)} {s.slot}" for s in all_slots[:5])
        + "。"
    )
    if min_minutes > 0:
        dropped = len(all_slots) - len(useful)
        lines.append(
            f"- 其中 {len(useful)} 段不短于 {format_duration(min_minutes)}；"
            f"另外 {dropped} 段是课间那十几分钟的空档（比如两节课之间休 15 分钟），"
            f"基本没法拿来安排事情，用 `--min-minutes {min_minutes}` 可以过滤掉。"
        )
    lines.append("")
    lines.append("复现命令：")
    lines.append("")
    lines.append("```bash")
    lines.append(
        "python main.py common --csv data/同学A课表.csv --csv data/同学B课表.csv"
        + (f" --min-minutes {min_minutes}" if min_minutes else "")
    )
    lines.append("```")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成共同空闲时段报告")
    parser.add_argument(
        "--csv", action="append", default=None, metavar="文件", help="课表路径，可重复"
    )
    parser.add_argument("--day-start", default="08:00", help="每天可用的开始时间，默认 08:00")
    parser.add_argument("--day-end", default="22:00", help="每天可用的结束时间，默认 22:00")
    parser.add_argument(
        "--min-minutes", type=int, default=60, help="结论里认为「够用」的最短时长，默认 60"
    )
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="输出路径")
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    paths = args.csv or DEFAULT_CSVS
    day_start, day_end = parse_time(args.day_start), parse_time(args.day_end)
    if day_start >= day_end:
        raise SystemExit(f"✗ 可用时间范围非法：{args.day_start}-{args.day_end}")

    people = load_people(paths)
    report = build_report(people, day_start, day_end, args.min_minutes, paths)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(report)
    print(f"✓ 已生成 {args.output}（{len(report)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
