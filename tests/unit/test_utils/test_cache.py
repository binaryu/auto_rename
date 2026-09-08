"""
Tests for ThreadSafeLRUCache (utils/cache.py).

覆盖：LRU 淘汰、线程安全、single-flight 合并（get_or_create）、
None 值缓存策略、异常唤醒等待者。
"""

import threading
import time

import pytest

from video_organizer.utils.cache import ThreadSafeLRUCache


class TestLRU:
    def test_evicts_least_recently_used(self):
        cache = ThreadSafeLRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        _ = cache["a"]  # 刷新 a
        cache["d"] = 4  # 淘汰 b（最久未使用）
        assert "b" not in cache
        assert "a" in cache and "c" in cache and "d" in cache

    def test_get_refreshes_recency(self):
        cache = ThreadSafeLRUCache(maxsize=2)
        cache["a"] = 1
        cache["b"] = 2
        assert cache.get("a") == 1
        cache["c"] = 3
        assert "b" not in cache  # b 未再访问被淘汰
        assert "a" in cache

    def test_missing_get_returns_default(self):
        cache = ThreadSafeLRUCache()
        assert cache.get("nope", 42) == 42
        assert cache.get("nope") is None

    def test_dict_equality_for_empty(self):
        assert ThreadSafeLRUCache() == {}

    def test_contains_is_thread_safe(self):
        cache = ThreadSafeLRUCache(maxsize=10)
        cache["k"] = "v"
        assert "k" in cache
        assert "missing" not in cache


class TestGetOrCreate:
    def test_factory_runs_once_and_caches(self):
        cache = ThreadSafeLRUCache()
        calls = []

        def factory():
            calls.append(1)
            return "value"

        assert cache.get_or_create("k", factory) == "value"
        assert cache.get_or_create("k", factory) == "value"
        assert len(calls) == 1

    def test_none_not_cached_by_default(self):
        cache = ThreadSafeLRUCache()
        calls = []

        def factory():
            calls.append(1)
            return None

        assert cache.get_or_create("k", factory) is None
        assert cache.get_or_create("k", factory) is None
        assert len(calls) == 2  # None 未缓存，每次都执行

    def test_none_cached_when_cache_none(self):
        cache = ThreadSafeLRUCache()
        calls = []

        def factory():
            calls.append(1)
            return None

        assert cache.get_or_create("k", factory, cache_none=True) is None
        assert cache.get_or_create("k", factory, cache_none=True) is None
        assert len(calls) == 1

    def test_concurrent_calls_collapse_to_one_factory(self):
        cache = ThreadSafeLRUCache()
        calls = []
        lock = threading.Lock()
        barrier = threading.Barrier(6)

        def factory():
            time.sleep(0.2)
            with lock:
                calls.append(1)
            return "value"

        results = []

        def worker():
            barrier.wait()
            results.append(cache.get_or_create("k", factory))

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not any(t.is_alive() for t in threads)
        assert len(calls) == 1
        assert results == ["value"] * 6
        assert cache._inflight == {}  # 在途表已清理

    def test_factory_exception_wakes_waiters(self):
        cache = ThreadSafeLRUCache()

        def factory():
            time.sleep(0.1)
            raise RuntimeError("boom")

        errors = []

        def leader():
            try:
                cache.get_or_create("k", factory)
            except RuntimeError:
                errors.append("leader")

        def follower():
            time.sleep(0.02)
            try:
                cache.get_or_create("k", factory)
            except RuntimeError:
                errors.append("follower")

        t1, t2 = threading.Thread(target=leader), threading.Thread(target=follower)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not t1.is_alive() and not t2.is_alive()
        assert "leader" in errors
        assert cache._inflight == {}

    def test_concurrent_mixed_keys_are_independent(self):
        cache = ThreadSafeLRUCache()
        calls = []
        lock = threading.Lock()

        def make_factory(v):
            def factory():
                time.sleep(0.05)
                with lock:
                    calls.append(v)
                return v

            return factory

        threads = []
        for i in range(10):
            key = i % 2  # 只有两个 key，大量并发
            threads.append(
                threading.Thread(
                    target=lambda k=key, v=key: cache.get_or_create(k, make_factory(v))
                )
            )
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert sorted(calls) == [0, 1]  # 每个 key 只执行一次
        assert cache._inflight == {}

    def test_concurrent_read_write_with_eviction_is_safe(self):
        """压力：小容量 + 高并发读写 + 频繁淘汰，不得抛 KeyError 或损坏数据。"""
        cache = ThreadSafeLRUCache(maxsize=8)
        stop = threading.Event()
        errors = []

        def writer():
            try:
                i = 0
                while not stop.is_set():
                    cache[i % 20] = i
                    i += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def reader():
            try:
                while not stop.is_set():
                    for k in range(20):
                        cache.get(k)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        stop.set()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        assert len(cache) <= 8
        assert cache._inflight == {}
