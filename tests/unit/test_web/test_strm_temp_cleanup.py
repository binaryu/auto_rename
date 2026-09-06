"""123 秒传临时文件清理的单元测试

回归点：秒传成功后 FileId 已分配，若取直链失败或 fs_trash 静默失败，
文件会残留在网盘**目录**里（不在回收站，定时清理盖不到）。
"""

import pytest

from video_organizer.web.routers.strm import _p123_handle_redirect, _p123_trash_temp


class TrashSpy:
    """记录 fs_trash 调用并按脚本返回结果的 client 桩"""

    def __init__(
        self,
        trash_results=(),
        upload_response=None,
        download_url="https://cdn.example.com/video.mkv",
        download_error=None,
    ):
        self.trash_calls = []
        self._trash_results = list(trash_results)
        self._upload_response = upload_response or {
            "code": 0,
            "data": {"Reuse": True, "FileId": 4321, "S3KeyFlag": "k"},
        }
        self._download_url = download_url
        self._download_error = download_error

    def upload_request(self, **kwargs):
        return self._upload_response

    def get_download_info(self, file_info):
        if self._download_error:
            raise self._download_error
        return self._download_url

    def fs_trash(self, file_id):
        self.trash_calls.append(file_id)
        if self._trash_results:
            result = self._trash_results.pop(0)
        else:
            result = {"code": 0, "message": "ok"}
        if isinstance(result, Exception):
            raise result
        return result


def make_client(**kwargs):
    """构造只返回指定 code 的 client 桩（用于 _p123_trash_temp 单测）"""

    class _OnlyTrash:
        def __init__(self, results):
            self.calls = []
            self.results = list(results)

        def fs_trash(self, file_id):
            self.calls.append(file_id)
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    return _OnlyTrash(kwargs.get("results", []))


# ========== _p123_trash_temp ==========


class TestTrashTemp:
    def test_success_on_first_attempt(self):
        client = make_client(results=[{"code": 0, "message": "ok"}])
        assert _p123_trash_temp(client, 111, "a.mkv") is True
        assert client.calls == [111]

    def test_string_file_id_is_coerced(self):
        client = make_client(results=[{"code": 0}])
        assert _p123_trash_temp(client, "222", "a.mkv") is True
        assert client.calls == [222]

    def test_retries_on_silent_api_error(self):
        """request() 失败时不抛异常，必须靠返回值判断并重试"""
        client = make_client(
            results=[
                {"code": 7308, "message": "文件不存在"},
                {"code": 0, "message": "ok"},
            ]
        )
        assert _p123_trash_temp(client, 333, "a.mkv") is True
        assert client.calls == [333, 333]

    def test_gives_up_after_two_attempts(self):
        client = make_client(
            results=[
                {"code": 500, "message": "服务异常"},
                {"code": 500, "message": "服务异常"},
            ]
        )
        assert _p123_trash_temp(client, 444, "a.mkv") is False
        assert len(client.calls) == 2

    def test_exception_is_retried(self):
        client = make_client(
            results=[RuntimeError("连接被重置"), {"code": 200, "message": "ok"}]
        )
        assert _p123_trash_temp(client, 555, "a.mkv") is True
        assert len(client.calls) == 2

    def test_code_200_counts_as_success(self):
        client = make_client(results=[{"code": 200}])
        assert _p123_trash_temp(client, 666, "a.mkv") is True


# ========== _p123_handle_redirect 的清理路径 ==========


@pytest.fixture
def p123_state(monkeypatch):
    """给 _p123_handle_redirect 装上可编排的 handler/client"""

    def _install(client):
        class _Uploader:
            pass

        class _Handler:
            pass

        uploader = _Uploader()
        uploader.client = client
        handler = _Handler()
        handler.p123_uploader = uploader

        from video_organizer.web.services.state import get_state_manager

        state = get_state_manager()
        monkeypatch.setattr(state, "get_video_handler", lambda: handler)
        monkeypatch.setattr(state, "get_config", lambda: {"p123": {"parent_id": 0}})
        return client

    return _install


class TestHandleRedirectCleanup:
    """无论取直链成功与否，秒传出来的临时文件都必须被清理"""

    def test_trashes_on_success(self, p123_state):
        client = p123_state(TrashSpy())
        response = _p123_handle_redirect(
            file_size=1024,
            etag="etag-success-1",
            file_name="movie.mkv",
            client_ip="10.0.0.1",
            s3keyflag="k",
        )
        assert response.status_code == 302
        assert client.trash_calls == [4321]

    def test_trashes_when_download_info_raises(self, p123_state):
        client = p123_state(TrashSpy(download_error=RuntimeError("超时")))
        response = _p123_handle_redirect(
            file_size=1024,
            etag="etag-err-1",
            file_name="movie.mkv",
            client_ip="10.0.0.2",
            s3keyflag="k",
        )
        assert response.status_code == 500
        assert client.trash_calls == [4321], "取直链异常时残留文件必须清理"

    def test_trashes_when_download_url_empty(self, p123_state):
        client = p123_state(TrashSpy(download_url=""))
        response = _p123_handle_redirect(
            file_size=1024,
            etag="etag-empty-1",
            file_name="movie.mkv",
            client_ip="10.0.0.3",
            s3keyflag="k",
        )
        assert response.status_code == 500
        assert client.trash_calls == [4321], "直链为空时残留文件必须清理"

    def test_no_trash_when_reuse_miss(self, p123_state):
        """未命中秒传时根本没有创建文件，不应调用 fs_trash"""
        client = p123_state(
            TrashSpy(upload_response={"code": 0, "data": {"Reuse": False}})
        )
        response = _p123_handle_redirect(
            file_size=1024,
            etag="etag-noreuse-1",
            file_name="movie.mkv",
            client_ip="10.0.0.4",
            s3keyflag="k",
        )
        assert response.status_code == 500
        assert client.trash_calls == []

    def test_no_trash_when_upload_fails(self, p123_state):
        client = p123_state(TrashSpy(upload_response={"code": 400, "message": "拒绝"}))
        response = _p123_handle_redirect(
            file_size=1024,
            etag="etag-uploadfail-1",
            file_name="movie.mkv",
            client_ip="10.0.0.5",
            s3keyflag="k",
        )
        assert response.status_code == 500
        assert client.trash_calls == []

    def test_no_trash_when_file_id_missing(self, p123_state):
        client = p123_state(
            TrashSpy(upload_response={"code": 0, "data": {"Reuse": True}})
        )
        response = _p123_handle_redirect(
            file_size=1024,
            etag="etag-nofileid-1",
            file_name="movie.mkv",
            client_ip="10.0.0.6",
            s3keyflag="k",
        )
        assert response.status_code == 500
        assert client.trash_calls == []

    def test_playback_still_succeeds_when_trash_fails(self, p123_state):
        """清理失败不能影响播放：仍然返回 302，只是会记残留告警"""
        client = p123_state(
            TrashSpy(
                trash_results=[
                    {"code": 500, "message": "服务异常"},
                    {"code": 500, "message": "服务异常"},
                ]
            )
        )
        response = _p123_handle_redirect(
            file_size=1024,
            etag="etag-trashfail-1",
            file_name="movie.mkv",
            client_ip="10.0.0.7",
            s3keyflag="k",
        )
        assert response.status_code == 302
        assert response.headers["location"] == "https://cdn.example.com/video.mkv"
        assert len(client.trash_calls) == 2

    def test_cached_url_skips_second_upload(self, p123_state):
        """同一 IP + etag 命中缓存时不再秒传，也就不再产生新的临时文件"""
        client = p123_state(TrashSpy())
        common = dict(
            file_size=1024,
            etag="etag-cache-1",
            file_name="movie.mkv",
            client_ip="10.0.0.8",
            s3keyflag="k",
        )
        assert _p123_handle_redirect(**common).status_code == 302
        assert _p123_handle_redirect(**common).status_code == 302
        assert client.trash_calls == [4321], "命中缓存不应再次秒传并删除"
