"""基础模型的单元测试。"""

import unittest

from timetable.models import (
    WEEKDAYS,
    Course,
    TimeSlot,
    Timetable,
    format_duration,
    format_time,
    gap_between,
    merge_intervals,
    parse_time,
    parse_weekday,
    weekday_name,
)


class ParseWeekdayTests(unittest.TestCase):
    def test_chinese_forms(self):
        self.assertEqual(parse_weekday("周一"), 0)
        self.assertEqual(parse_weekday("星期一"), 0)
        self.assertEqual(parse_weekday("礼拜天"), 6)
        self.assertEqual(parse_weekday("周日"), 6)

    def test_numeric_and_english(self):
        self.assertEqual(parse_weekday("1"), 0)
        self.assertEqual(parse_weekday("7"), 6)
        self.assertEqual(parse_weekday("Monday"), 0)
        self.assertEqual(parse_weekday("sun"), 6)

    def test_strips_whitespace(self):
        self.assertEqual(parse_weekday("  周三  "), 2)

    def test_unknown_raises(self):
        for bad in ("星期几", "", "第八天", "weekday"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_weekday(bad)

    def test_weekday_name_roundtrip(self):
        for index, name in enumerate(WEEKDAYS):
            self.assertEqual(weekday_name(index), name)
            self.assertEqual(parse_weekday(name), index)

    def test_weekday_name_out_of_range(self):
        with self.assertRaises(ValueError):
            weekday_name(7)


class ParseTimeTests(unittest.TestCase):
    def test_various_formats(self):
        self.assertEqual(parse_time("08:30"), 510)
        self.assertEqual(parse_time("8:05"), 485)
        self.assertEqual(parse_time("8：05"), 485)  # 全角冒号
        self.assertEqual(parse_time("8.05"), 485)
        self.assertEqual(parse_time("0800"), 480)
        self.assertEqual(parse_time("800"), 480)
        self.assertEqual(parse_time("8"), 480)

    def test_bounds(self):
        self.assertEqual(parse_time("00:00"), 0)
        self.assertEqual(parse_time("23:59"), 1439)

    def test_invalid(self):
        for bad in ("24:00", "08:60", "abc", "", "-1:00"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_time(bad)

    def test_format_time(self):
        self.assertEqual(format_time(0), "00:00")
        self.assertEqual(format_time(510), "08:30")
        self.assertEqual(format_time(1439), "23:59")

    def test_format_duration(self):
        self.assertEqual(format_duration(45), "45 分")
        self.assertEqual(format_duration(60), "1 小时")
        self.assertEqual(format_duration(135), "2 小时 15 分")


class TimeSlotTests(unittest.TestCase):
    def test_rejects_empty_or_reversed(self):
        with self.assertRaises(ValueError):
            TimeSlot(600, 600)
        with self.assertRaises(ValueError):
            TimeSlot(600, 500)

    def test_rejects_out_of_day(self):
        with self.assertRaises(ValueError):
            TimeSlot(-1, 100)
        with self.assertRaises(ValueError):
            TimeSlot(100, 24 * 60 + 1)

    def test_duration_and_str(self):
        slot = TimeSlot(540, 585)
        self.assertEqual(slot.duration, 45)
        self.assertEqual(str(slot), "09:00-09:45")

    def test_adjacent_is_not_overlap(self):
        """09:00-10:00 和 10:00-11:00 是首尾相接，不算重叠 —— 这是空闲时段算对的关键。"""
        self.assertFalse(TimeSlot(540, 600).overlaps(TimeSlot(600, 660)))
        self.assertEqual(gap_between(TimeSlot(540, 600), TimeSlot(600, 660)), 0)

    def test_overlap_and_gap(self):
        self.assertTrue(TimeSlot(540, 600).overlaps(TimeSlot(570, 630)))
        self.assertEqual(gap_between(TimeSlot(540, 585), TimeSlot(595, 640)), 10)

    def test_merge(self):
        self.assertEqual(
            str(TimeSlot(540, 585).merge(TimeSlot(595, 640))), "09:00-10:40"
        )

    def test_slice(self):
        slot = TimeSlot(480, 600)
        self.assertEqual(str(slot.slice(540, 660)), "09:00-10:00")
        self.assertIsNone(slot.slice(700, 800))

    def test_parse(self):
        self.assertEqual(TimeSlot.parse("08:00 - 12:00"), TimeSlot(480, 720))
        with self.assertRaises(ValueError):
            TimeSlot.parse("08:00")


class MergeIntervalsTests(unittest.TestCase):
    def test_keeps_small_gaps_by_default(self):
        merged = merge_intervals([TimeSlot(540, 585), TimeSlot(595, 640)])
        self.assertEqual([str(s) for s in merged], ["09:00-09:45", "09:55-10:40"])

    def test_merges_within_tolerance(self):
        merged = merge_intervals([TimeSlot(540, 585), TimeSlot(595, 640)], tolerance=15)
        self.assertEqual([str(s) for s in merged], ["09:00-10:40"])

    def test_unions_overlaps(self):
        merged = merge_intervals([TimeSlot(540, 600), TimeSlot(570, 660)])
        self.assertEqual([str(s) for s in merged], ["09:00-11:00"])

    def test_sorts_input(self):
        merged = merge_intervals([TimeSlot(600, 660), TimeSlot(480, 540)])
        self.assertEqual([str(s) for s in merged], ["08:00-09:00", "10:00-11:00"])

    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])


class CourseTests(unittest.TestCase):
    def _course(self, **kwargs):
        payload = dict(name="高等数学", weekday=0, start=540, end=640)
        payload.update(kwargs)
        return Course(**payload)

    def test_basic(self):
        course = self._course(location=" 致理楼A302 ")
        self.assertEqual(course.location, "致理楼A302")  # 自动 strip
        self.assertEqual(course.duration, 100)
        self.assertEqual(str(course.slot), "09:00-10:40")

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            self._course(name="   ")

    def test_bad_weekday_rejected(self):
        with self.assertRaises(ValueError):
            self._course(weekday=7)

    def test_reversed_time_rejected(self):
        with self.assertRaises(ValueError):
            self._course(start=640, end=540)

    def test_with_slot_keeps_name(self):
        grown = self._course().with_slot(TimeSlot(540, 640))
        self.assertEqual(grown.name, "高等数学")
        self.assertEqual(grown.end, 640)


class TimetableTests(unittest.TestCase):
    def test_add_course_parses_strings(self):
        table = Timetable("张三")
        table.add_course("高等数学", "周一", "09:00", "10:40", "致理楼A302")
        self.assertEqual(len(table), 1)
        self.assertEqual(table.courses[0].weekday, 0)
        self.assertEqual(table.courses[0].end, 640)

    def test_courses_on_sorted(self):
        table = Timetable()
        table.add_course("B", "周一", "14:00", "15:00")
        table.add_course("A", "周一", "09:00", "10:00")
        self.assertEqual([c.name for c in table.courses_on("周一")], ["A", "B"])

    def test_courses_by_day_has_seven_keys(self):
        table = Timetable()
        table.add_course("A", "周三", "09:00", "10:00")
        by_day = table.courses_by_day()
        self.assertEqual(sorted(by_day), list(range(7)))
        self.assertEqual(len(by_day[2]), 1)
        self.assertEqual(by_day[0], [])

    def test_busy_days(self):
        table = Timetable()
        table.add_course("A", "周五", "09:00", "10:00")
        table.add_course("B", "周一", "09:00", "10:00")
        table.add_course("C", "周五", "14:00", "15:00")
        self.assertEqual(table.busy_days, [0, 4])

    def test_extend_returns_self(self):
        table = Timetable()
        self.assertIs(table.extend([Course("A", 0, 540, 600)]), table)

    def test_add_rejects_non_course(self):
        with self.assertRaises(TypeError):
            Timetable().add("不是课程")


if __name__ == "__main__":
    unittest.main()
