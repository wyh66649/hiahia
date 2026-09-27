"""共同空闲时段（需求 3）的单元测试。

重点验证两件事：
1. 交集算得对（三个人都能凑上的时间才算数）；
2. 结果按「越长越靠前」排序。
"""

import unittest

from timetable.common import (
    CommonSlot,
    common_free_slots,
    intersect_slots,
    render_common_slots,
)
from timetable.models import TimeSlot, Timetable
from timetable.slots import daily_free_slots

DAY_START = 8 * 60
DAY_END = 22 * 60


def table(owner, rows):
    """rows: [(课程名, 星期几, 开始, 结束), ...]"""
    result = Timetable(owner)
    for name, weekday, start, end in rows:
        result.add_course(name, weekday, start, end)
    return result


class IntersectSlotsTests(unittest.TestCase):
    def test_simple_overlap(self):
        left = [TimeSlot(480, 600)]
        right = [TimeSlot(540, 700)]
        self.assertEqual([str(s) for s in intersect_slots(left, right)], ["09:00-10:00"])

    def test_multiple_pieces(self):
        left = [TimeSlot(480, 600), TimeSlot(660, 720)]
        right = [TimeSlot(540, 700)]
        self.assertEqual(
            [str(s) for s in intersect_slots(left, right)], ["09:00-10:00", "11:00-11:40"]
        )

    def test_no_overlap(self):
        self.assertEqual(intersect_slots([TimeSlot(480, 540)], [TimeSlot(600, 660)]), [])

    def test_touching_is_not_overlap(self):
        self.assertEqual(intersect_slots([TimeSlot(480, 540)], [TimeSlot(540, 600)]), [])

    def test_empty_side(self):
        self.assertEqual(intersect_slots([], [TimeSlot(480, 540)]), [])

    def test_identical(self):
        slots = [TimeSlot(480, 600)]
        self.assertEqual(intersect_slots(slots, slots), slots)


class CommonFreeSlotsTests(unittest.TestCase):
    def setUp(self):
        # 张三：周一 09:00-10:40 高数（两节连上）、周一 14:00-15:40 英语
        self.a = table(
            "张三",
            [
                ("高等数学", "周一", "09:00", "09:45"),
                ("高等数学", "周一", "09:55", "10:40"),
                ("大学英语", "周一", "14:00", "15:40"),
            ],
        )
        # 李四：周一 10:00-11:40 数据结构
        self.b = table("李四", [("数据结构", "周一", "10:00", "11:40")])

    def test_intersection_of_two(self):
        slots = common_free_slots([self.a, self.b], DAY_START, DAY_END)
        monday = [str(item.slot) for item in slots if item.weekday == 0]
        self.assertEqual(monday, ["15:40-22:00", "11:40-14:00", "08:00-09:00"])

    def test_sorted_by_duration_desc(self):
        slots = common_free_slots([self.a, self.b], DAY_START, DAY_END)
        durations = [item.duration for item in slots]
        self.assertEqual(durations, sorted(durations, reverse=True))

    def test_tie_broken_by_weekday_then_start(self):
        """同样长度时，星期靠前的排前面。"""
        slots = common_free_slots([self.a, self.b], DAY_START, DAY_END)
        keys = [(-item.duration, item.weekday, item.start) for item in slots]
        self.assertEqual(keys, sorted(keys))

    def test_only_common_time_counts(self):
        """甲有课、乙没课的时间，不算共同空闲。"""
        slots = common_free_slots([self.a, self.b], DAY_START, DAY_END)
        # 09:00-10:40 张三有课，必然不在结果里
        for item in slots:
            if item.weekday == 0:
                self.assertFalse(item.start < 10 * 60 + 40 and item.end > 9 * 60)

    def test_three_people(self):
        c = table("王五", [("线性代数", "周一", "16:00", "18:00")])
        slots = common_free_slots([self.a, self.b, c], DAY_START, DAY_END)
        monday = [str(item.slot) for item in slots if item.weekday == 0]
        # 王五 16:00-18:00 有课，所以 15:40-18:00 被切掉，只剩 15:40-16:00 这一小段
        self.assertEqual(
            monday, ["18:00-22:00", "11:40-14:00", "08:00-09:00", "15:40-16:00"]
        )

    def test_disjoint_people_give_nothing(self):
        busy_all_day = table("卷王", [("自习", "周一", "08:00", "22:00")])
        slots = common_free_slots([self.a, busy_all_day], DAY_START, DAY_END)
        self.assertEqual([item for item in slots if item.weekday == 0], [])

    def test_single_person_matches_personal_free_slots(self):
        shared = common_free_slots([self.a], DAY_START, DAY_END)
        personal = daily_free_slots(self.a, DAY_START, DAY_END)
        expected = sorted(
            (slot.duration for slot in personal[0]), reverse=True
        )
        monday = [item.duration for item in shared if item.weekday == 0]
        self.assertEqual(monday, expected)

    def test_min_minutes_filters(self):
        slots = common_free_slots([self.a, self.b], DAY_START, DAY_END, min_minutes=120)
        self.assertTrue(all(item.duration >= 120 for item in slots))

    def test_empty_input_raises(self):
        with self.assertRaises(ValueError):
            common_free_slots([], DAY_START, DAY_END)

    def test_merge_flag_matters(self):
        """关掉合并后，张三周一会漏出 09:45-09:55 这段，共同空闲就会变多。"""
        merged = common_free_slots([self.a, self.b], DAY_START, DAY_END, merge=True)
        raw = common_free_slots([self.a, self.b], DAY_START, DAY_END, merge=False)
        self.assertLess(len(merged), len(raw))

    def test_str_and_properties(self):
        item = CommonSlot(2, TimeSlot(540, 640))
        self.assertEqual(str(item), "周三 09:00-10:40")
        self.assertEqual(item.duration, 100)
        self.assertEqual((item.start, item.end), (540, 640))

    def test_custom_window(self):
        slots = common_free_slots([self.a, self.b], 18 * 60, 21 * 60)
        monday = [str(item.slot) for item in slots if item.weekday == 0]
        self.assertEqual(monday, ["18:00-21:00"])


class SampleDataTests(unittest.TestCase):
    """用仓库里的两份示例课表跑一遍，锁定端到端的排序结果。"""

    @classmethod
    def setUpClass(cls):
        import os

        from timetable.loader import load_csv

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.a = load_csv(os.path.join(root, "data", "student_a.csv"))
        cls.b = load_csv(os.path.join(root, "data", "student_b.csv"))

    def test_expected_ranking(self):
        slots = common_free_slots([self.a, self.b], DAY_START, DAY_END)
        got = [(item.weekday, str(item.slot)) for item in slots]
        expected = [
            (6, "08:00-22:00"),   # 840 分钟
            (4, "09:40-22:00"),   # 740
            (2, "11:40-22:00"),   # 620
            (5, "11:40-22:00"),   # 620
            (0, "15:40-22:00"),   # 380
            (1, "15:40-22:00"),   # 380
            (3, "09:40-16:00"),   # 380
            (1, "09:40-14:00"),   # 260
            (3, "17:40-22:00"),   # 260
            (0, "11:40-14:00"),   # 140
            (2, "08:00-10:00"),   # 120
            (0, "08:00-09:00"),   # 60
            (5, "08:00-09:00"),   # 60
        ]
        self.assertEqual(got, expected)

    def test_first_result_is_longest(self):
        slots = common_free_slots([self.a, self.b], DAY_START, DAY_END)
        self.assertEqual(slots[0].duration, max(item.duration for item in slots))


class RenderCommonSlotsTests(unittest.TestCase):
    def _tables(self):
        a = table("张三", [("高等数学", "周一", "09:00", "10:40")])
        b = table("李四", [("数据结构", "周一", "10:00", "11:40")])
        return [a, b]

    def test_renders_ranking(self):
        tables = self._tables()
        text = render_common_slots(tables, day_start=DAY_START, day_end=DAY_END)
        self.assertIn("共同空闲时段 · 2 人", text)
        self.assertIn("张三、李四", text)
        self.assertIn("按空闲时长降序", text)
        self.assertIn("1.", text)
        self.assertIn("段可共同安排的时间", text)

    def test_renders_empty_note(self):
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        full = [(f"自习{day}", day, "08:00", "22:00") for day in weekdays]
        text = render_common_slots(
            [table("张三", full), table("李四", full)], day_start=DAY_START, day_end=DAY_END
        )
        self.assertIn("没有一个人人都有空的时段", text)

    def test_top_limits_rows(self):
        tables = self._tables()
        text = render_common_slots(
            tables, day_start=DAY_START, day_end=DAY_END, top=1
        )
        self.assertIn("只显示了最长的 1 段", text)


if __name__ == "__main__":
    unittest.main()
