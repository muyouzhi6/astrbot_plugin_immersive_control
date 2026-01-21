# core/data.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TypedDict

from astrbot.core.utils.plugin_kv_store import PluginKVStoreMixin

from .config import PluginConfig


class SessionDict(TypedDict, total=False):
    is_active: bool
    end_at: float
    activated_at: float
    ts: float
    reason: str
    item_name: str
    sensitivity: int


@dataclass(slots=True)
class SessionRecord:
    is_active: bool
    item_name: str

    # active-only
    sensitivity: int | None = None
    end_at: float | None = None
    activated_at: float | None = None

    # exit-pending-only
    ts: float | None = None
    reason: str | None = None

    # ========= 构造 =========

    @classmethod
    def active(
        cls,
        *,
        duration: int,
        item_name: str,
        sensitivity: int,
    ) -> "SessionRecord":  # noqa: UP037
        now = time.time()
        return cls(
            is_active=True,
            item_name=item_name,
            sensitivity=sensitivity,
            activated_at=now,
            end_at=now + duration,
        )

    @classmethod
    def exit_pending(
        cls,
        *,
        reason: str,
        item_name: str,
    ) -> "SessionRecord":  # noqa: UP037
        return cls(
            is_active=False,
            item_name=item_name,
            reason=reason,
            ts=time.time(),
        )

    # ========= 状态判断 =========

    def is_expired_active(self, now: float) -> bool:
        return self.is_active and self.end_at is not None and self.end_at <= now

    def is_expired_exit(self, now: float, ttl: int) -> bool:
        return not self.is_active and self.ts is not None and now - self.ts > ttl

    # ========= 序列化 =========

    def to_dict(self) -> SessionDict:
        data: SessionDict = {
            "is_active": self.is_active,
            "item_name": self.item_name,
        }

        if self.sensitivity is not None:
            data["sensitivity"] = self.sensitivity
        if self.end_at is not None:
            data["end_at"] = self.end_at
        if self.activated_at is not None:
            data["activated_at"] = self.activated_at
        if self.ts is not None:
            data["ts"] = self.ts
        if self.reason is not None:
            data["reason"] = self.reason

        return data

    @classmethod
    def from_dict(cls, raw: SessionDict) -> "SessionRecord | None":  # noqa: UP037
        is_active = raw.get("is_active")
        if not isinstance(is_active, bool):
            return None

        return cls(
            is_active=is_active,
            item_name=raw.get("item_name", "特殊装置"),
            sensitivity=raw.get("sensitivity"),
            end_at=raw.get("end_at"),
            activated_at=raw.get("activated_at"),
            ts=raw.get("ts"),
            reason=raw.get("reason"),
        )


class SessionStore(PluginKVStoreMixin):
    KV_STATES = "immersive_states"
    KV_COOLDOWNS = "immersive_cooldowns"

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.plugin_id = self.cfg.plugin_id
        self._state_lock = asyncio.Lock()
        self._cooldown_lock = asyncio.Lock()

    # ========= KV =========

    async def _load_states(self) -> dict[str, SessionRecord]:
        raw = await self.get_kv_data(self.KV_STATES, {}) or {}
        result: dict[str, SessionRecord] = {}
        for k, v in raw.items():
            rec = SessionRecord.from_dict(v)
            if rec:
                result[k] = rec
        return result

    async def _save_states(self, states: dict[str, SessionRecord]):
        await self.put_kv_data(
            self.KV_STATES,
            {k: v.to_dict() for k, v in states.items()},
        )

    async def _load_cooldowns(self) -> dict[str, float]:
        return await self.get_kv_data(self.KV_COOLDOWNS, {}) or {}

    async def _save_cooldowns(self, cooldowns: dict[str, float]):
        await self.put_kv_data(self.KV_COOLDOWNS, cooldowns)

    # ========= 清理 =========

    def _cleanup_states(
        self, states: dict[str, SessionRecord]
    ) -> tuple[dict[str, SessionRecord], bool]:
        now = time.time()
        changed = False
        new_states: dict[str, SessionRecord] = {}

        for key, rec in states.items():
            if rec.is_expired_active(now):
                new_states[key] = SessionRecord.exit_pending(
                    reason="expire",
                    item_name=rec.item_name,
                )
                changed = True
            elif rec.is_expired_exit(now, self.cfg.exit_pending_ttl):
                changed = True
            else:
                new_states[key] = rec

        return new_states, changed

    # ========= 对外 API =========

    async def get(self, key: str) -> SessionRecord | None:
        async with self._state_lock:
            states = await self._load_states()
            states, changed = self._cleanup_states(states)
            if changed:
                await self._save_states(states)
            return states.get(key)

    async def activate(self, key: str) -> tuple[bool, str]:
        async with self._state_lock:
            states = await self._load_states()
            states, _ = self._cleanup_states(states)

            now = time.time()
            active_count = sum(1 for s in states.values() if s.is_active)
            if active_count >= self.cfg.max_concurrent_states:
                return False, "并发上限"

            states[key] = SessionRecord.active(
                duration=self.cfg.state_duration_seconds,
                item_name=self.cfg.interactive_item_name,
                sensitivity=self.cfg.sensitivity_level,
            )
            await self._save_states(states)

        async with self._cooldown_lock:
            cds = await self._load_cooldowns()
            cds[key] = now + self.cfg.cooldown_seconds
            await self._save_cooldowns(cds)

        return True, "ok"

    async def deactivate(self, key: str) -> bool:
        async with self._state_lock:
            states = await self._load_states()
            rec = states.get(key)
            if not rec or not rec.is_active:
                return False

            states[key] = SessionRecord.exit_pending(
                reason="user",
                item_name=rec.item_name,
            )
            await self._save_states(states)
            return True

    async def complete_exit(self, key: str) -> SessionRecord | None:
        async with self._state_lock:
            states = await self._load_states()
            rec = states.get(key)
            if not rec or rec.is_active:
                return None
            del states[key]
            await self._save_states(states)
            return rec

    async def check_cooldown(self, key: str) -> int:
        async with self._cooldown_lock:
            cds = await self._load_cooldowns()
            now = time.time()
            end = cds.get(key, 0)
            return max(0, int(end - now))
