"""
logging_utils 文件日志标识功能的单元测试
"""

import logging
import threading

import pytest

from video_organizer.utils import logging_utils
from video_organizer.utils.logging_utils import (
    LOG_FORMAT,
    DATE_FORMAT,
    TaskIdFilter,
    TaskIdFormatter,
)


@pytest.fixture(autouse=True)
def _clean_file_id():
    """每个用例前后清除文件日志标识，避免跨用例污染"""
    logging_utils.clear_file_id()
    yield
    logging_utils.clear_file_id()


class TestMakeFileId:
    """make_file_id 的编号与截断逻辑"""

    def test_short_name_kept_unchanged(self):
        fid = logging_utils.make_file_id("爱恋.S01E01.mkv")
        assert fid.startswith("#")
        assert fid.endswith("爱恋.S01E01.mkv")
        assert "…" not in fid

    def test_windows_path_uses_basename(self):
        fid = logging_utils.make_file_id(r"D:\downloads\爱恋.S01E01.mkv")
        assert fid.endswith("爱恋.S01E01.mkv")
        assert "downloads" not in fid

    def test_long_name_truncated_middle(self):
        long_name = "This.Is.A.Very.Long.Show.Name.2023.S01E01.1080p.BluRay.x264-GROUP.mkv"
        fid = logging_utils.make_file_id(long_name)
        name_part = fid.split(" ", 1)[1]
        assert len(name_part) == 48
        assert "…" in name_part
        # 保留开头（片名）和结尾（画质/扩展名）
        assert name_part.startswith("This.Is.A.Very.Long.Show")
        assert name_part.endswith("GROUP.mkv")

    def test_sequence_number_increases(self):
        first = logging_utils.make_file_id("a.mkv")
        second = logging_utils.make_file_id("b.mkv")
        num1 = int(first.split(" ", 1)[0][1:])
        num2 = int(second.split(" ", 1)[0][1:])
        assert num2 > num1


class TestSetAndClearFileId:
    """set_file_id / clear_file_id / get_file_id"""

    def test_default_empty(self):
        assert logging_utils.get_file_id() == ""

    def test_set_then_get(self):
        logging_utils.set_file_id("爱恋.S01E01.mkv")
        assert logging_utils.get_file_id().endswith("爱恋.S01E01.mkv")

    def test_set_is_idempotent(self):
        logging_utils.set_file_id("a.mkv")
        first = logging_utils.get_file_id()
        logging_utils.set_file_id("b.mkv")  # 已设置，不应重新分配编号
        assert logging_utils.get_file_id() == first
        assert first.endswith("a.mkv")

    def test_clear_resets(self):
        logging_utils.set_file_id("x.mkv")
        logging_utils.clear_file_id()
        assert logging_utils.get_file_id() == ""

    def test_file_id_is_thread_local(self):
        logging_utils.set_file_id("main.mkv")
        seen = []
        t = threading.Thread(target=lambda: seen.append(logging_utils.get_file_id()))
        t.start()
        t.join()
        assert seen == [""]  # 子线程不继承主线程的文件标识
        assert logging_utils.get_file_id() != ""


class TestWithFileId:
    """with_file_id 前缀"""

    def test_no_prefix_when_unset(self):
        assert logging_utils.with_file_id("你好") == "你好"

    def test_prefix_when_set(self):
        logging_utils.set_file_id("爱恋.S01E01.mkv")
        out = logging_utils.with_file_id("处理完成")
        assert out.startswith("[")
        assert out.endswith("处理完成")


class TestTaskIdFormatter:
    """TaskIdFormatter 在日志行前渲染文件标识"""

    def _format(self, msg: str) -> str:
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, msg, (), None
        )
        TaskIdFilter().filter(record)
        return TaskIdFormatter(LOG_FORMAT, DATE_FORMAT).format(record)

    def test_prefix_when_file_id_set(self):
        logging_utils.set_file_id("爱恋.S01E01.mkv")
        out = self._format("hello")
        assert out.startswith(f"[{logging_utils.get_file_id()}] ")
        assert out.endswith(" - hello")

    def test_no_prefix_when_file_id_empty(self):
        out = self._format("hello")
        assert not out.startswith("[")
        assert out.endswith(" - hello")
