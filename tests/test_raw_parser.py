"""教务系统导出（网格）课表的解析测试。"""

import csv
import io
import os
import unittest

from timetable.loader import load_csv, load_text
from timetable.raw_parser import (
    deduplicate,
    looks_like_grid,
    parse_cell,
    parse_grid_text,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_SAMPLE = os.path.join(ROOT, "data", "同学A课表.csv")

HEADER = ["节次/星期", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

PERIOD_MATH = "第二双节第1小节09:00-09:45\n(09:00-09:45)"
PERIOD_ENG = "第三双节第1小节10:45-11:30\n(10:45-11:30)"

MATH_CELL = "工科数学分析Ⅰ 07\n1-4周,6-18周 程老师 09:00-10:30 【1-210】"
ENG_CELL = "大学英语（A-1） 07\n1-4周,6-16周 吴老师 10:45-12:15 【1-208】"
MULTI_CELL = (
    "大学生心理健康教育 05\n3周 王老师 08:00-10:30 【3-227】\n"
    "6周 李老师 08:00-10:30 【3-227】\n"
    "8周 赵老师 08:00-10:30 【3-227】"
)


def build_grid(rows, title="2026-2027学年 第一学期 示例同学[1120260000] 课表", footer=True):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([title] + [""] * 7)
    writer.writerow(HEADER)
    for label, cells in rows:
        writer.writerow([label] + [cells.get(day, "") for day in range(7)])
    if footer:
        writer.writerow(["打印人：示例同学    打印时间：2026-09-26 22:14"] + [""] * 7)
    return buffer.getvalue()


SIMPLE_GRID = build_grid([
    (PERIOD_MATH, {0: MATH_CELL, 2: MATH_CELL}),
    ("第二双节第2小节09:46-10:30\n(09:46-10:30)", {}),
    (PERIOD_ENG, {4: ENG_CELL}),
])

STANDARD_CSV = "课程名,星期几,开始时间,结束时间\n高等数学,周一,09:00,10:40\n"


class FormatSniffingTests(unittest.TestCase):
    def test_detects_grid(self):
        self.assertTrue(looks_like_grid(SIMPLE_GRID))

    def test_standard_csv_is_not_grid(self):
        """标准表头里也有「星期」二字，不能被误判成网格格式。"""
        self.assertFalse(looks_like_grid(STANDARD_CSV))

    def test_standard_csv_imports_as_standard(self):
        table = load_text(STANDARD_CSV, owner="张三")
        self.assertEqual(len(table), 1)
        self.assertEqual(table.courses[0].name, "高等数学")


class ParseCellTests(unittest.TestCase):
    def test_empty_cell(self):
        self.assertEqual(parse_cell("", 0), [])
        self.assertEqual(parse_cell("   \n ", 0), [])

    def test_single_course(self):
        records = parse_cell(MATH_CELL, 0)
        self.assertEqual(len(records), 1)
        course = records[0].course
        self.assertEqual(course.name, "工科数学分析Ⅰ")   # 课程编号 07 被去掉
        self.assertEqual(str(course.slot), "09:00-10:30")
        self.assertEqual(course.location, "1-210")
        self.assertEqual(records[0].teacher, "程老师")
        self.assertEqual(records[0].weeks, "1-4周,6-18周")

    def test_multi_detail_lines_merge_into_one_course(self):
        """同一门课的不同周次写成多行（3周/6周/8周），要并成一条，别拆成三门课。"""
        records = parse_cell(MULTI_CELL, 1)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.course.name, "大学生心理健康教育")
        self.assertEqual(str(record.course.slot), "08:00-10:30")
        self.assertEqual(record.weeks, "3周、6周、8周")
        self.assertEqual(record.teacher, "王老师/李老师/赵老师")
        self.assertEqual(record.course.weekday, 1)

    def test_name_keeps_trailing_digits_that_are_part_of_name(self):
        records = parse_cell("形势与政策1、2 06\n2周 袁老师 15:45-17:15 【3-228】", 5)
        self.assertEqual(records[0].course.name, "形势与政策1、2")

    def test_falls_back_to_period_label_when_cell_has_no_time(self):
        records = parse_cell("体育 08\n任课教师待定 【体育馆】", 3, PERIOD_MATH)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].course.name, "体育")
        self.assertEqual(str(records[0].course.slot), "09:00-09:45")
        self.assertEqual(records[0].course.location, "体育馆")

    def test_skips_entry_without_any_time(self):
        self.assertEqual(parse_cell("体育 08\n任课教师待定", 3), [])


class ParseGridTextTests(unittest.TestCase):
    def test_parses_simple_grid(self):
        parsed = parse_grid_text(SIMPLE_GRID)
        self.assertEqual(parsed.owner, "示例同学")
        self.assertEqual(parsed.student_id, "1120260000")
        self.assertEqual(parsed.term, "2026-2027学年 第一学期")
        self.assertEqual(len(parsed.records), 3)

    def test_footer_is_not_parsed_as_course(self):
        parsed = parse_grid_text(SIMPLE_GRID)
        self.assertNotIn("打印人", {r.course.name for r in parsed.records})

    def test_bad_header_raises(self):
        with self.assertRaises(ValueError):
            parse_grid_text("课程名,星期几,开始时间,结束时间\n高等数学,周一,09:00,10:40\n")

    def test_header_without_data_raises(self):
        text = build_grid([], footer=False)
        with self.assertRaises(ValueError):
            parse_grid_text(text)

    def test_deduplicate(self):
        records = parse_cell(MULTI_CELL, 1) + parse_cell(MULTI_CELL, 1)
        self.assertEqual(len(records), 2)
        self.assertEqual(len(deduplicate(records)), 1)  # 同名同时间，只留一条


class RealTimetableFileTests(unittest.TestCase):
    """跑一遍仓库里的真实（已脱敏）教务课表，保证端到端可用。"""

    def setUp(self):
        if not os.path.exists(RAW_SAMPLE):
            self.skipTest("没有找到示例原始课表")
        self.table = load_csv(RAW_SAMPLE)

    def test_owner_falls_back_to_filename(self):
        """标题行里的姓名学号已抹掉，名字就取文件名。"""
        self.assertEqual(self.table.owner, "同学A")

    def test_course_count(self):
        self.assertEqual(len(self.table), 18)

    def test_sunday_has_three_courses(self):
        self.assertEqual(len(self.table.courses_on("周日")), 3)

    def test_no_course_on_saturday(self):
        self.assertEqual(self.table.courses_on("周六"), [])

    def test_multi_week_cell_merged_into_one(self):
        """周二一格的「大学生心理健康教育」写了 5 个不同周次，应当只有 1 条。"""
        tuesday = [c for c in self.table.courses_on("周二") if c.name == "大学生心理健康教育"]
        self.assertEqual(len(tuesday), 1)
        self.assertEqual(str(tuesday[0].slot), "08:00-10:30")

    def test_course_code_stripped(self):
        names = {c.name for c in self.table}
        self.assertIn("工科数学分析Ⅰ", names)
        self.assertNotIn("工科数学分析Ⅰ 07", names)


if __name__ == "__main__":
    unittest.main()
