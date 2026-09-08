"""
Tests for BaseCloudOrganizer.recognize_file_by_name renamer reuse.

回归目标：网盘整理逐文件调用 recognize_file_by_name 时，不应每个文件都
重新创建 VideoRenamer（否则 TMDB/LLM 缓存全部失效，同一目录的多集会
反复请求 TMDB 甚至 LLM）。
"""

from unittest.mock import patch

import pytest

from video_organizer.upload.base_organizer import BaseCloudOrganizer


@pytest.fixture
def organizer():
    return BaseCloudOrganizer(tmdb_api_key="fake_key")


class TestRenamerReuse:
    def test_renamer_created_once_across_calls(self, organizer):
        """连续两次识别，只创建一个 VideoRenamer 实例。"""
        with patch("video_organizer.core.renamer.VideoRenamer") as MockRenamer:
            renamer_instance = MockRenamer.return_value
            renamer_instance.extract_metadata.return_value = {
                "show_name": "早春晴朗",
                "year": "2026",
                "season": 1,
                "episode": 1,
                "tmdb_id": "999001",
                "media_type": "tv",
                "quality_tags": "",
                "release_group": "",
                "genres": ["剧情"],
                "origin_country": ["CN"],
            }
            renamer_instance.tmdb_client.search_video_show.return_value = {
                "results": []
            }
            renamer_instance._determine_category.return_value = "TV Shows/电视剧"

            organizer.recognize_file_by_name("早春晴朗 2026 S01E01.mp4")
            organizer.recognize_file_by_name("早春晴朗 2026 S01E02.mp4")

            assert MockRenamer.call_count == 1
            assert organizer._renamer is renamer_instance

    def test_concurrent_calls_do_not_duplicate_creation(self, organizer):
        """并发首次调用也只创建一个实例（双重检查加锁）。"""
        import threading

        with patch("video_organizer.core.renamer.VideoRenamer") as MockRenamer:
            renamer_instance = MockRenamer.return_value
            renamer_instance.extract_metadata.return_value = {
                "show_name": "早春晴朗",
                "year": "2026",
                "season": 1,
                "episode": 1,
                "tmdb_id": "999001",
                "media_type": "tv",
                "quality_tags": "",
                "release_group": "",
                "genres": ["剧情"],
                "origin_country": ["CN"],
            }
            renamer_instance.tmdb_client.search_video_show.return_value = {
                "results": []
            }
            renamer_instance._determine_category.return_value = "TV Shows/电视剧"

            results = []
            barrier = threading.Barrier(4)

            def worker():
                barrier.wait()
                results.append(organizer.recognize_file_by_name("早春晴朗 S01E01.mp4"))

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert MockRenamer.call_count == 1

    def test_no_tmdb_key_skips_renamer(self, organizer):
        organizer.tmdb_api_key = None
        with patch("video_organizer.core.renamer.VideoRenamer") as MockRenamer:
            metadata = organizer.recognize_file_by_name("早春晴朗 S01E01.mp4")
            MockRenamer.assert_not_called()
            assert metadata["show_name"] == ""
