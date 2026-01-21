# typed_config.py
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, get_type_hints

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig


class ConfigNode:
    """配置节点：dict → 强类型属性访问（极简版）"""

    _SCHEMA_CACHE: dict[type, dict[str, type]] = {}

    @classmethod
    def _schema(cls) -> dict[str, type]:
        return cls._SCHEMA_CACHE.setdefault(cls, get_type_hints(cls))

    def __init__(self, data: MutableMapping[str, Any]):
        object.__setattr__(self, "_data", data)
        for key in self._schema():
            if key in data:
                continue
            if hasattr(self.__class__, key):
                continue
            logger.warning(f"[config:{self.__class__.__name__}] 缺少字段: {key}")

    def __getattr__(self, key: str) -> Any:
        if key in self._schema():
            return self._data.get(key)
        raise AttributeError(key)

    def __setattr__(self, key: str, value: Any) -> None:
        if key in self._schema():
            self._data[key] = value
            return
        object.__setattr__(self, key, value)


class PluginConfig(ConfigNode):
    admin_only_mode: bool
    enter_keywords: list[str]
    exit_keywords: list[str]
    state_duration: int
    cooldown_seconds: int
    max_concurrent: int
    item_name: str
    sensitivity: int
    enter_template: str
    exit_template: str

    def __init__(self, config: AstrBotConfig):
        super().__init__(config)
        self.exit_pending_ttl = 86400
