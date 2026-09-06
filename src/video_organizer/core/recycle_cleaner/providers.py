"""各网盘回收站 Provider 实现

目前实现：
- ``p123``    123云盘（``file/trash_delete_all`` 清空 / ``file/list/new?trashed=true`` 统计）

预留：yun139、cloud189 按同一接口补一个 Provider 即可接入。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional, Tuple

from .base import (
    BaseRecycleProvider,
    RecycleStats,
    register_provider,
)

logger = logging.getLogger(__name__)

__all__ = ["P123RecycleProvider"]


@register_provider
class P123RecycleProvider(BaseRecycleProvider):
    """123云盘回收站"""

    name = "p123"
    label = "123云盘"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        client: Optional[Any] = None,
    ) -> None:
        super().__init__(config)
        self._client = client
        self._client_lock = threading.Lock()

    # ----- 凭据 / 客户端 -----

    @property
    def _section(self) -> Dict[str, Any]:
        return self.config.get("p123", {}) or {}

    def _credentials(self) -> Tuple[str, str, str]:
        section = self._section
        return (
            self._clean_credential(section.get("token")),
            self._clean_credential(section.get("username")),
            self._clean_credential(section.get("password")),
        )

    def is_available(self) -> bool:
        if self._client is not None:
            return True
        token, username, password = self._credentials()
        return bool(token or (username and password))

    def _get_client(self):
        """惰性创建 Pan123Client（token 失效时由 Pan123Client 自动重新登录）"""
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is None:
                from ...upload.pan123_client import Pan123Client

                token, username, password = self._credentials()
                self._client = Pan123Client(
                    token=token, username=username, password=password
                )
        return self._client

    # ----- 能力实现 -----

    def stats(self, max_items: int = 5000) -> RecycleStats:
        stats = RecycleStats(provider=self.name)
        if not self.is_available():
            stats.available = False
            stats.error = "未配置 123云盘 凭据（[p123] token 或 username/password）"
            return stats
        try:
            raw = self._get_client().recycle_stats(max_items=max_items)
        except Exception as exc:  # 网络/认证异常均降级为错误
            logger.warning(f"[{self.name}] 读取回收站统计失败: {exc}")
            stats.error = str(exc)
            return stats
        stats.count = int(raw.get("count", 0) or 0)
        stats.size = int(raw.get("size", 0) or 0)
        stats.truncated = bool(raw.get("truncated"))
        return stats

    def clear(self) -> Tuple[bool, str]:
        if not self.is_available():
            return False, "未配置 123云盘 凭据（[p123] token 或 username/password）"
        try:
            resp = self._get_client().recycle_clear()
        except Exception as exc:
            logger.error(f"[{self.name}] 清空回收站异常: {exc}")
            return False, str(exc)
        code = resp.get("code")
        message = str(resp.get("message") or "")
        if code in (0, 200):
            logger.info(f"[{self.name}] 回收站已清空")
            return True, message or "回收站已清空"
        logger.warning(f"[{self.name}] 清空回收站失败: code={code} {message}")
        return False, message or f"清空失败（code={code}）"
