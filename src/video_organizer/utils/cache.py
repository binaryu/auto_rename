"""线程安全的 LRU 缓存容器，带 single-flight 合并（get_or_create）。"""

import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional

# 哨兵：区分「缓存未命中」与「缓存值为 None」
_MISS = object()


class ThreadSafeLRUCache(OrderedDict):
    """容量有上限、线程安全、按访问刷新（LRU）的缓存。

    - 所有读写操作内部加锁，并发安全（消除 check-then-act 竞态）
    - 超出 maxsize 自动淘汰最久未使用的条目（防止长跑内存膨胀）
    - get_or_create() 提供 single-flight：同 key 的并发调用合并为一次
      factory 执行，其余调用等待并复用其结果

    用法与 dict 基本一致（get / in / [] / keys / popitem 等），
    因此可作为现有 dict 缓存的直接替换。
    """

    def __init__(self, maxsize: int = 2000):
        super().__init__()
        self.maxsize = max(int(maxsize), 1)
        self._lock = threading.RLock()
        self._inflight: Dict[Any, threading.Event] = {}

    # -------------------- 基础 dict 接口（线程安全 + LRU 刷新） --------------------

    def __getitem__(self, key):
        with self._lock:
            value = super().__getitem__(key)
            self.move_to_end(key)
            return value

    def __setitem__(self, key, value):
        with self._lock:
            super().__setitem__(key, value)
            self.move_to_end(key)
            if len(self) > self.maxsize:
                self.popitem(last=False)

    def __contains__(self, key) -> bool:
        with self._lock:
            return super().__contains__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def setdefault(self, key, default=None):
        """线程安全的 setdefault（仅当 key 不存在时写入，不刷新 LRU）。"""
        with self._lock:
            if key not in self:
                self[key] = default
            return self[key]

    def pop(self, key, default=None):
        """线程安全的 pop。"""
        with self._lock:
            if key in self:
                value = super().__getitem__(key)
                super().__delitem__(key)
                return value
            return default

    def clear(self) -> None:
        """线程安全的 clear。"""
        with self._lock:
            super().clear()

    # -------------------- single-flight --------------------

    def get_or_create(
        self,
        key,
        factory: Callable[[], Any],
        cache_none: bool = False,
        wait_timeout: Optional[float] = None,
    ):
        """命中缓存直接返回；未命中时由首个调用执行 factory 并写缓存。

        Args:
            key: 缓存键
            factory: 计算结果的可调用对象（仅在 leader 线程执行一次）
            cache_none: factory 返回 None 时是否也写入缓存
                （如「无法解析」的结果也值得缓存，避免反复查询）
            wait_timeout: 等待在途请求的最长时间（秒）；None 表示无限等待

        Returns:
            factory 的计算结果；等待者复用 leader 的结果。
            factory 返回 None 且 cache_none=False 时不写缓存，返回 None。
        """
        value = self.get(key, _MISS)
        if value is not _MISS:
            return value

        with self._lock:
            # 双重检查：可能在等待锁期间已被其他线程写入
            value = self.get(key, _MISS)
            if value is not _MISS:
                return value
            event = self._inflight.get(key)
            if event is None:
                event = threading.Event()
                self._inflight[key] = event
                is_leader = True
            else:
                is_leader = False

        if not is_leader:
            # 等待者：复用 leader 的结果（leader 异常/完成都会 set）
            if wait_timeout is not None:
                event.wait(timeout=wait_timeout)
            else:
                event.wait()
            value = self.get(key, _MISS)
            return None if value is _MISS else value

        try:
            value = factory()
        except Exception:
            # 异常时必须唤醒等待者，避免死等
            with self._lock:
                self._inflight.pop(key, None)
            event.set()
            raise

        if cache_none or value is not None:
            self[key] = value
        with self._lock:
            self._inflight.pop(key, None)
        event.set()
        return value
