"""空闲时段计算（需求 2）的单元测试。

重点验证需求里点名的这件事：同一课程连续两节要合并，
不能凭空冒出一个 09:45-09:55 的碎片空闲。
"""

import unittest

from timetable.models import Course, TimeSlot, Timetable
from timetable.slots import (
    DEFAULT_MERGE_GAP,
    busy_slots,
    daily_free_slots,
    free_slots,
    merge_courses,
    merged_courses_by_day,
    render_free_slots,
)


def course(name, weekday, start, end, location=""):
    return Course(
        name=name,
        weekday=weekday,
        start=start,
        end=end,
        location=location,
    )


class MergeCoursesTests(unittest.TestCase):
    def test_merges_consecutive_periods_of_same_course(self):
        """09:00-09:45 + 09:55-10:40（中间休息 10 分钟）-> 09:00-10:40"""
        merged = merge_courses([course("高等数学", 0, 540, 585), course("高等数学", 0, 595, 640)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(str(merged[0].slot), "09:00-10:40")
        self.assertEqual(merged[0].name, "高等数学")

    def test_keeps_location(self):
        merged = merge_courses(
            [
                course("高等数学", 0, 540, 585, "致理楼A302"),
                course("高等数学", 0, 595, 640, "致理楼A302"),
            ]
        )
        self.assertEqual(merged[0].location, "致理楼A302")

    def test_does_not_merge_different_courses(self):
        merged = merge_courses([course("高等数学", 0, 540, 600), course("大学英语", 0, 600, 660)])
        self.assertEqual([c.name for c in merged], ["高等数学", "大学英语"])
        self.assertEqual(len(merged), 2)

    def test_does_not_merge_across_days(self):
        merged = merge_courses([course("高等数学", 0, 540, 585), course("高等数学", 1, 595, 640)])
        self.assertEqual(len(merged), 2)

    def test_gap_threshold_is_respected(self):
        far = [course("高等数学", 0, 540, 585), course("高等数学", 0, 700, 745)]
        self.assertEqual(len(merge_courses(far)), 2)
        self.assertEqual(len(merge_courses(far, max_gap=200)), 1)

    def test_tolerance_can_be_tightened_to_zero(self):
        two = [course("高等数学", 0, 540, 585), course("高等数学", 0, 595, 640)]
        self.assertEqual(len(merge_courses(two, max_gap=0)), 2)

    def test_merges_overlapping_periods(self):
        merged = merge_courses([course("高等数学", 0, 540, 600), course("高等数学", 0, 570, 660)])
        self.assertEqual(str(merged[0].slot), "09:00-11:00")

    def test_merges_more_than_two_periods(self):
        periods = [
            course("实验", 5, 540, 585),
            course("实验", 5, 595, 640),
            course("实验", 5, 650, 695),
        ]
        merged = merge_courses(periods)
        self.assertEqual(len(merged), 1)
        self.assertEqual(str(merged[0].slot), "09:00-11:35")

    def test_output_is_sorted(self):
        merged = merge_courses([course("B", 1, 600, 660), course("A", 0, 540, 600)])
        self.assertEqual([(c.weekday, c.name) for c in merged], [(0, "A"), (1, "B")])

    def test_empty(self):
        self.assertEqual(merge_courses([]), [])

    def test_default_gap_is_fifteen(self):
        self.assertEqual(DEFAULT_MERGE_GAP, 15)

    def test_merged_courses_by_day_has_seven_keys(self):
        table = Timetable()
        table.add_course("A", "周一", "09:00", "10:40")
        by_day = merged_courses_by_day(table)
        self.assertEqual(sorted(by_day), list(range(7)))
        self.assertEqual(len(by_day[0]), 1)


class BusySlotsTests(unittest.TestCase):
    def test_unions_overlapping_courses(self):
        busy = busy_slots([course("A", 0, 540, 600), course("B", 0, 570, 660)])
        self.assertEqual([str(s) for s in busy], ["09:00-11:00"])

    def test_adjacent_courses_become_one_block(self):
        busy = busy_slots([course("A", 0, 540, 600), course("B", 0, 600, 660)])
        self.assertEqual([str(s) for s in busy], ["09:00-11:00"])

    def test_merges_consecutive_periods_first(self):
        busy = busy_slots([course("高数", 0, 540, 585), course("高数", 0, 595, 640)])
        self.assertEqual([str(s) for s in busy], ["09:00-10:40"])


class FreeSlotsTests(unittest.TestCase):
    def test_basic(self):
        free = free_slots([TimeSlot(540, 600)], 480, 720)
        self.assertEqual([str(s) for s in free], ["08:00-09:00", "10:00-12:00"])

    def test_busy_outside_window_is_ignored(self):
        free = free_slots([TimeSlot(400, 460)], 480, 720)
        self.assertEqual([str(s) for s in free], ["08:00-12:00"])

    def test_busy_crossing_the_window_edge_is_clipped(self):
        free = free_slots([TimeSlot(600, 800)], 480, 720)
        self.assertEqual([str(s) for s in free], ["08:00-10:00"])

    def test_fully_occupied_day(self):
        self.assertEqual(free_slots([TimeSlot(480, 720)], 480, 720), [])

    def test_empty_busy_means_whole_window_is_free(self):
        self.assertEqual([str(s) for s in free_slots([], 480, 720)], ["08:00-12:00"])

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            free_slots([], 720, 480)


class DailyFreeSlotsTests(unittest.TestCase):
    def _table(self):
        table = Timetable("张三")
        table.add_course("高等数学", "周一", "09:00", "09:45", "致理楼A302")
        table.add_course("高等数学", "周一", "09:55", "10:40", "致理楼A302")
        return table

    def test_no_fragment_when_merged(self):
        """合并后不该冒出 09:45-09:55 这种 10 分钟的碎片。"""
        free = daily_free_slots(self._table(), 8 * 60, 12 * 60, merge=True)
        self.assertEqual([str(s) for s in free[0]], ["08:00-09:00", "10:40-12:00"])

    def test_fragment_shows_up_when_not_merged(self):
        """关掉合并就能看到碎片 —— 用来证明合并确实起了作用。"""
        free = daily_free_slots(self._table(), 8 * 60, 12 * 60, merge=False)
        self.assertEqual(
            [str(s) for s in free[0]], ["08:00-09:00", "09:45-09:55", "10:40-12:00"]
        )

    def test_all_seven_days_present(self):
        free = daily_free_slots(Timetable(), 8 * 60, 22 * 60)
        self.assertEqual(sorted(free), list(range(7)))
        self.assertEqual([str(s) for s in free[3]], ["08:00-22:00"])

    def test_min_minutes_filters_short_slots(self):
        table = Timetable()
        table.add_course("A", "周一", "08:00", "09:00")
        table.add_course("B", "周一", "09:10", "09:50")  # 夹出一个 10 分钟的空档
        free = daily_free_slots(table, 8 * 60, 12 * 60, min_minutes=30)
        self.assertEqual([str(s) for s in free[0]], ["09:50-12:00"])

    def test_min_minutes_zero_keeps_everything(self):
        table = Timetable()
        table.add_course("A", "周一", "08:00", "09:00")
        table.add_course("B", "周一", "09:10", "09:50")
        free = daily_free_slots(table, 8 * 60, 12 * 60, min_minutes=0)
        self.assertEqual([str(s) for s in free[0]], ["09:00-09:10", "09:50-12:00"])

    def test_custom_window(self):
        free = daily_free_slots(Timetable(), 9 * 60, 18 * 60)
        self.assertEqual([str(s) for s in free[0]], ["09:00-18:00"])


class RenderFreeSlotsTests(unittest.TestCase):
    def test_renders_day_headers_and_durations(self):
        table = Timetable("张三")
        table.add_course("高等数学", "周一", "09:00", "10:40")
        text = render_free_slots(table, day_start=8 * 60, day_end=12 * 60)
        self.assertIn("张三 的空闲时段", text)
        self.assertIn("08:00 - 12:00", text)
        self.assertIn("【周一】", text)
        self.assertIn("08:00-09:00", text)
        self.assertIn("【周日】", text)

    def test_renders_full_day_note(self):
        table = Timetable()
        table.add_course("满课", "周二", "08:00", "22:00")
        text = render_free_slots(table, day_start=8 * 60, day_end=22 * 60)
        self.assertIn("全被占满", text)


if __name__ == "__main__":
    unittest.main()
