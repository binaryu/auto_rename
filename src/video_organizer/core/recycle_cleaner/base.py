"""回收站清理框架 - 数据模型与 Provider 抽象

各网盘的回收站语义并不一致（123 的"删除"是移入回收站、彻底删除需要额外接口；
天翼云盘有独立的 empty_recycle），因此这里只约定两个能力：

- ``stats()``  查询回收站条目数与占用空间
- ``clear()``  清空回收站（彻底删除，不可恢复）

调度、通知、状态记录由 :mod:`.cleaner` 统一实现，新增网盘只需实现一个 Provider。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

__all__ = [
    "RecycleStats",
    "CleanResult",
    "BaseRecycleProvider",
    "register_provider",
    "get_provider_class",
    "list_provider_names",
    "create_provider",
]


def format_size(num_bytes: int) -> str:
    """把字节数格式化为便于阅读的字符串（用于日志与通知）"""
    try:
        size = float(num_bytes or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return "0 B"


@dataclass
class RecycleStats:
    """回收站统计结果"""

    provider: str
    available: bool = True
    count: int = 0
    size: int = 0
    truncated: bool = False
    error: str = ""

    @property
    def size_text(self) -> str:
        return format_size(self.size)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "count": self.count,
            "size": self.size,
            "size_text": self.size_text,
            "truncated": self.truncated,
            "error": self.error,
        }


@dataclass
class CleanResult:
    """一次清理的结果"""

    provider: str
    success: bool = False
    skipped: bool = False
    dry_run: bool = False
    count: int = 0
    size: int = 0
    message: str = ""
    started_at: str = ""
    finished_at: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def size_text(self) -> str:
        return format_size(self.size)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "success": self.success,
            "skipped": self.skipped,
            "dry_run": self.dry_run,
            "count": self.count,
            "size": self.size,
            "size_text": self.size_text,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "details": self.details,
        }


class BaseRecycleProvider:
    """网盘回收站 Provider 基类"""

    #: 唯一标识，同时用作配置项 providers 的取值
    name: str = ""
    #: 界面展示名
    label: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = config or {}

    # ----- 子类必须实现 -----

    def is_available(self) -> bool:
        """凭据是否齐全（不发起网络请求）"""
        raise NotImplementedError

    def stats(self, max_items: int = 5000) -> RecycleStats:
        """查询回收站条目数与占用空间"""
        raise NotImplementedError

    def clear(self) -> "tuple[bool, str]":
        """清空回收站，返回 (是否成功, 说明文本)"""
        raise NotImplementedError

    # ----- 通用辅助 -----

    @staticmethod
    def _clean_credential(value: Any) -> str:
        """配置值可能带行内注释（``#`` / ``;``），与 handler 的处理保持一致"""
        if value is None:
            return ""
        return str(value).split("#")[0].split(";")[0].strip()


_PROVIDER_REGISTRY: Dict[str, Type[BaseRecycleProvider]] = {}


def register_provider(cls: Type[BaseRecycleProvider]) -> Type[BaseRecycleProvider]:
    """注册 Provider（类装饰器）"""
    if not cls.name:
        raise ValueError("Provider 必须定义 name")
    _PROVIDER_REGISTRY[cls.name] = cls
    return cls


def get_provider_class(name: str) -> Optional[Type[BaseRecycleProvider]]:
    return _PROVIDER_REGISTRY.get(name)


def list_provider_names() -> List[str]:
    return sorted(_PROVIDER_REGISTRY.keys())


def create_provider(
    name: str, section_configs: Optional[Dict[str, Any]] = None
) -> BaseRecycleProvider:
    """按名称创建 Provider

    Args:
        name: Provider 名称（如 ``p123``）
        section_configs: 完整配置字典（``{section: {...}}``），Provider 自行取用所需 section

    Raises:
        ValueError: 未注册的 Provider
    """
    cls = _PROVIDER_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"不支持的网盘类型: {name}")
    return cls(section_configs or {})
