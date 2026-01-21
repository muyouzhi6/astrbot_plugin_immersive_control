from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .config import PluginConfig


@dataclass(slots=True)
class Session:
    active: bool
    """是否处于激活状态"""

    end: float | None = None
    """激活结束时间戳"""

    exit_ts: float | None = None
    """进入 exit-pending 的时间戳"""

    reason: str | None = None
    """退出原因：user / expire"""

    cooldown_end: float = 0.0
    """冷却结束时间戳"""


class SessionStore:
    """会话状态内存缓存"""

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self._data: dict[str, Session] = {}
        """key -> Session"""

        self._lock = asyncio.Lock()
        """状态与冷却统一锁"""

    # ================= 内部 =================

    def _cleanup_one(self, key: str):
        """惰性清理单个会话（仅在访问时触发）"""
        s = self._data.get(key)
        if not s:
            return

        now = time.time()

        # active 超时 → 转 exit-pending
        if s.active and s.end is not None and s.end <= now:
            s.active = False
            s.exit_ts = now
            s.reason = "expire"

        # exit-pending 超时 → 彻底移除
        elif not s.active and s.exit_ts is not None:
            if now - s.exit_ts > self.cfg.exit_pending_ttl:
                self._data.pop(key, None)

    # ================= API =================

    async def get(self, key: str) -> Session | None:
        """获取当前会话状态（会触发惰性清理）"""
        async with self._lock:
            self._cleanup_one(key)
            return self._data.get(key)

    async def activate(self, key: str) -> tuple[bool, str]:
        """激活会话（受并发与冷却限制）"""
        async with self._lock:
            now = time.time()
            self._cleanup_one(key)

            active_count = sum(1 for s in self._data.values() if s.active)
            if active_count >= self.cfg.max_concurrent:
                return False, "并发上限"

            self._data[key] = Session(
                active=True,
                end=now + self.cfg.state_duration,
                cooldown_end=now + self.cfg.cooldown_seconds,
            )
            return True, "ok"

    async def deactivate(self, key: str) -> bool:
        """手动退出会话"""
        async with self._lock:
            s = self._data.get(key)
            if not s or not s.active:
                return False

            s.active = False
            s.exit_ts = time.time()
            s.reason = "user"
            return True

    async def complete_exit(self, key: str) -> Session | None:
        """完成退出并移除会话（用于外部消费 exit 信息）"""
        async with self._lock:
            s = self._data.get(key)
            if not s or s.active:
                return None
            return self._data.pop(key)

    async def check_cooldown(self, key: str) -> int:
        """获取剩余冷却秒数"""
        async with self._lock:
            s = self._data.get(key)
            if not s:
                return 0
            return max(0, int(s.cooldown_end - time.time()))
