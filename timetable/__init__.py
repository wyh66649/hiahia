"""课表解析与空闲时段计算。

对外 API::

    from timetable import load_csv, render_timetable, daily_free_slots

    tt = load_csv("data/student_a.csv")
    print(render_timetable(tt))
    print(daily_free_slots(tt, 8 * 60, 22 * 60))

模块划分：

===================  ==================================================
``models``           时间 / 时间段 / 课程 / 课表的基础模型
``loader``           读入层：标准 CSV、教务网格 CSV、手动录入
``raw_parser``       教务系统导出格式的解析细节
``display``          文本视图渲染（按天列表 / 周视图）
``slots``            合并连续节次 + 计算每日空闲时段
``common``           多份课表求共同空闲时段
===================  ==================================================
"""

from .common import CommonSlot, common_free_slots, intersect_slots, render_common_slots
from .display import display_width, pad, render_grid, render_timetable, truncate
from .loader import (
    STANDARD_FIELDS,
    TimetableFormatError,
    load_csv,
    load_many,
    load_text,
    owner_from_filename,
    prompt_manual_timetable,
    read_text_file,
)
from .models import (
    MINUTES_PER_DAY,
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
from .raw_parser import RawCourse, RawTimetable, looks_like_grid, parse_grid_text
from .slots import (
    DEFAULT_DAY_END,
    DEFAULT_DAY_START,
    DEFAULT_MERGE_GAP,
    busy_slots,
    daily_free_slots,
    free_slots,
    merge_courses,
    merged_courses_by_day,
    render_free_slots,
)

__version__ = "0.3.0"

__all__ = [
    # 模型
    "Course",
    "TimeSlot",
    "Timetable",
    "WEEKDAYS",
    "MINUTES_PER_DAY",
    "parse_time",
    "parse_weekday",
    "weekday_name",
    "format_time",
    "format_duration",
    "gap_between",
    "merge_intervals",
    # 读入
    "load_csv",
    "load_many",
    "load_text",
    "read_text_file",
    "owner_from_filename",
    "prompt_manual_timetable",
    "TimetableFormatError",
    "STANDARD_FIELDS",
    # 原始课表
    "looks_like_grid",
    "parse_grid_text",
    "RawCourse",
    "RawTimetable",
    # 渲染
    "render_timetable",
    "render_grid",
    "display_width",
    "pad",
    "truncate",
    # 空闲时段
    "merge_courses",
    "merged_courses_by_day",
    "busy_slots",
    "free_slots",
    "daily_free_slots",
    "render_free_slots",
    "DEFAULT_MERGE_GAP",
    "DEFAULT_DAY_START",
    "DEFAULT_DAY_END",
    # 共同空闲
    "CommonSlot",
    "common_free_slots",
    "intersect_slots",
    "render_common_slots",
    "__version__",
]
