"""课表解析与空闲时段计算。

对外 API::

    from timetable import Timetable, load_csv, render_timetable

    tt = load_csv("data/student_a.csv")
    print(render_timetable(tt))

模块划分：

===================  ==================================================
``models``           时间 / 时间段 / 课程 / 课表的基础模型
``loader``           读入层：标准 CSV、教务网格 CSV、手动录入
``raw_parser``       教务系统导出格式的解析细节
``display``          文本视图渲染（按天列表 / 周视图）
===================  ==================================================
"""

from .display import display_width, pad, render_grid, render_timetable, truncate
from .loader import (
    STANDARD_FIELDS,
    TimetableFormatError,
    load_csv,
    load_many,
    load_text,
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

__version__ = "0.1.0"

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
    "__version__",
]
