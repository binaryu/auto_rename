"""网盘回收站定时清理

- ``base``      Provider 抽象与数据模型
- ``providers`` 各网盘实现（当前：123云盘）
- ``cleaner``   每日时间点调度器（含启动补跑、手动触发、Telegram 通知）

用法::

    from src.video_organizer.core.recycle_cleaner import RecycleCleaner

    cleaner = RecycleCleaner(config)
    cleaner.start()
"""

from .base import (
    BaseRecycleProvider,
    CleanResult,
    RecycleStats,
    create_provider,
    format_size,
    get_provider_class,
    list_provider_names,
    register_provider,
)
from .cleaner import (
    RecycleCleaner,
    get_cleaner,
    has_missed_slot,
    next_slot_time,
    parse_time_slots,
    set_cleaner,
)
from .providers import P123RecycleProvider

__all__ = [
    "BaseRecycleProvider",
    "CleanResult",
    "RecycleStats",
    "RecycleCleaner",
    "P123RecycleProvider",
    "create_provider",
    "register_provider",
    "get_provider_class",
    "list_provider_names",
    "format_size",
    "parse_time_slots",
    "next_slot_time",
    "has_missed_slot",
    "get_cleaner",
    "set_cleaner",
]
