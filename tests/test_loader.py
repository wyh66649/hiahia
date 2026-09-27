"""读入层的单元测试（标准 CSV / 手动录入 / 编码识别）。"""

import os
import tempfile
import unittest

from timetable.loader import (
    TimetableFormatError,
    load_csv,
    load_text,
    prompt_manual_timetable,
    read_text_file,
)

STANDARD = """课程名,星期几,开始时间,结束时间,地点
高等数学,周一,09:00,09:45,致理楼A302
高等数学,周一,09:55,10:40,致理楼A302
大学英语,星期三,14:00,15:40,文科楼B105
"""


class StandardFormatTests(unittest.TestCase):
    def test_basic(self):
        table = load_text(STANDARD, owner="张三")
        self.assertEqual(table.owner, "张三")
        self.assertEqual(len(table), 3)
        self.assertEqual(table.courses[0].name, "高等数学")
        self.assertEqual(table.courses[-1].weekday, 2)

    def test_header_aliases_and_reordered_columns(self):
        text = "课程,星期,起始时间,下课时间\n线性代数,周五,08:00,09:40\n"
        table = load_text(text)
        self.assertEqual(len(table), 1)
        self.assertEqual(table.courses[0].weekday, 4)

    def test_location_column_optional(self):
        table = load_text("课程名,星期几,开始时间,结束时间\n体育,周四,16:00,17:40\n")
        self.assertEqual(table.courses[0].location, "")

    def test_without_header_falls_back_to_positional(self):
        table = load_text("线性代数,周五,08:00,09:40,致理楼A205\n")
        course = table.courses[0]
        self.assertEqual((course.name, course.weekday, course.start), ("线性代数", 4, 480))

    def test_comments_and_blank_lines_skipped(self):
        text = STANDARD + "\n# 下面这行是注释\n\n"
        self.assertEqual(len(load_text(text)), 3)

    def test_missing_column_raises_with_hint(self):
        with self.assertRaises(TimetableFormatError) as ctx:
            load_text("课程名,星期几,开始时间\n高等数学,周一,09:00\n")
        self.assertIn("结束时间", str(ctx.exception))

    def test_empty_input_raises(self):
        with self.assertRaises(TimetableFormatError):
            load_text("   \n\n")

    def test_bad_rows_skipped_by_default(self):
        text = STANDARD + "坏课,第八天,25:00,26:00\n"
        table = load_text(text)  # 不应抛异常
        self.assertEqual(len(table), 3)

    def test_bad_rows_raise_in_strict_mode(self):
        text = STANDARD + "坏课,第八天,09:00,10:00\n"
        with self.assertRaises(TimetableFormatError) as ctx:
            load_text(text, strict=True)
        self.assertIn("第 5 行", str(ctx.exception))

    def test_all_rows_bad_raises(self):
        with self.assertRaises(TimetableFormatError):
            load_text("课程名,星期几,开始时间,结束时间\n坏课,第八天,09:00,10:00\n")


class FileEncodingTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="timetable-test-")

    def tearDown(self):
        for name in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, name))
        os.rmdir(self.tmpdir)

    def _write(self, name, text, encoding):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        return path

    def test_reads_utf8(self):
        path = self._write("a.csv", STANDARD, "utf-8")
        self.assertEqual(len(load_csv(path)), 3)

    def test_reads_utf8_with_bom(self):
        path = self._write("b.csv", STANDARD, "utf-8-sig")
        self.assertEqual(len(load_csv(path)), 3)

    def test_reads_gbk(self):
        """教务系统导出的文件基本都是 GBK，必须能自动识别。"""
        path = self._write("c.csv", STANDARD, "gbk")
        table = load_csv(path)
        self.assertEqual(len(table), 3)
        self.assertEqual(table.courses[0].name, "高等数学")

    def test_owner_defaults_to_filename(self):
        path = self._write("张三.csv", STANDARD, "utf-8")
        self.assertEqual(load_csv(path).owner, "张三")

    def test_explicit_owner_wins(self):
        path = self._write("xyz.csv", STANDARD, "utf-8")
        self.assertEqual(load_csv(path, owner="李四").owner, "李四")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_csv(os.path.join(self.tmpdir, "不存在.csv"))

    def test_read_text_file_with_explicit_encoding(self):
        path = self._write("d.csv", STANDARD, "gbk")
        self.assertIn("高等数学", read_text_file(path, encoding="gbk"))


class _ScriptedInput:
    """按脚本逐条返回答案；答案用光后抛 EOFError，模拟用户直接 Ctrl-D。"""

    def __init__(self, answers):
        self._answers = list(answers)

    def __call__(self, prompt=""):
        if not self._answers:
            raise EOFError()
        return self._answers.pop(0)


class ManualEntryTests(unittest.TestCase):
    def _run(self, answers):
        """把预设的答案喂给手动录入，返回 (课表, 屏幕输出)。"""
        printed = []
        table = prompt_manual_timetable(
            owner="张三",
            input_func=_ScriptedInput(answers),
            output_func=printed.append,
        )
        return table, "\n".join(printed)

    def test_enters_one_course(self):
        table, output = self._run(["高等数学", "周一", "09:00", "10:40", "致理楼A302", ""])
        self.assertEqual(len(table), 1)
        self.assertEqual(table.owner, "张三")
        self.assertIn("已加入", output)

    def test_reasks_until_valid(self):
        # 第一次时间填错，应该被追问，而不是直接崩
        table, output = self._run(
            ["大学英语", "周三", "25:00", "14:00", "15:40", "人文楼", ""]
        )
        self.assertEqual(len(table), 1)
        self.assertEqual(table.courses[0].start, 14 * 60)
        self.assertIn("✗", output)

    def test_end_before_start_is_rejected(self):
        table, _ = self._run(["体育", "1", "16:00", "15:00", "17:40", "", ""])
        self.assertEqual(table.courses[0].start, 16 * 60)
        self.assertEqual(table.courses[0].end, 17 * 60 + 40)

    def test_empty_name_finishes_immediately(self):
        table, _ = self._run([""])
        self.assertEqual(len(table), 0)

    def test_eof_finishes_gracefully(self):
        table, _ = self._run([])
        self.assertEqual(len(table), 0)

    def test_manual_entry_can_be_printed(self):
        from timetable.display import render_timetable

        table, _ = self._run(["高等数学", "2", "09:00", "10:40", "", ""])
        rendered = render_timetable(table)
        self.assertIn("周二", rendered)
        self.assertIn("高等数学", rendered)


if __name__ == "__main__":
    unittest.main()
