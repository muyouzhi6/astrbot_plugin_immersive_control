import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "immersive_control_testpkg"


def _load_module():
    for name in list(sys.modules):
        if name.startswith(PACKAGE_NAME) or name in {
            "astrbot",
            "astrbot.api",
            "astrbot.api.event",
            "astrbot.api.provider",
            "astrbot.core",
            "astrbot.core.config",
            "astrbot.core.config.astrbot_config",
            "astrbot.core.star",
            "astrbot.core.star.context",
        }:
            sys.modules.pop(name, None)

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = package

    astrbot = types.ModuleType("astrbot")
    astrbot.logger = types.SimpleNamespace(
        info=lambda *a, **k: None, debug=lambda *a, **k: None
    )
    sys.modules["astrbot"] = astrbot

    api = types.ModuleType("astrbot.api")
    api.logger = astrbot.logger
    sys.modules["astrbot.api"] = api

    class Filter:
        EventMessageType = types.SimpleNamespace(ALL="all")
        PermissionType = types.SimpleNamespace(ADMIN="admin")

        def __getattr__(self, name):
            def decorator_factory(*args, **kwargs):
                def decorator(func):
                    return func

                return decorator

            return decorator_factory

    event_mod = types.ModuleType("astrbot.api.event")
    event_mod.AstrMessageEvent = object
    event_mod.filter = Filter()
    sys.modules["astrbot.api.event"] = event_mod

    provider_mod = types.ModuleType("astrbot.api.provider")
    provider_mod.ProviderRequest = object
    sys.modules["astrbot.api.provider"] = provider_mod

    config_mod = types.ModuleType("astrbot.core.config.astrbot_config")
    config_mod.AstrBotConfig = dict
    sys.modules["astrbot.core.config.astrbot_config"] = config_mod
    sys.modules["astrbot.core.config"] = types.ModuleType("astrbot.core.config")

    class Star:
        def __init__(self, context):
            self.context = context

    star_mod = types.ModuleType("astrbot.core.star")
    star_mod.Star = Star
    sys.modules["astrbot.core.star"] = star_mod
    context_mod = types.ModuleType("astrbot.core.star.context")
    context_mod.Context = object
    sys.modules["astrbot.core.star.context"] = context_mod
    sys.modules["astrbot.core"] = types.ModuleType("astrbot.core")

    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.main", ROOT / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _Event:
    unified_msg_origin = "aiocqhttp:group:123"

    def __init__(self, text):
        self.message_str = text
        self.call_llm = False
        self.stopped = False

    def is_admin(self):
        return True

    def should_call_llm(self, value):
        self.call_llm = value

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return text


class _Store:
    def __init__(self, *, remaining=0, activate_result=(True, "ok")):
        self.remaining = remaining
        self.activate_result = activate_result
        self.activated = []
        self.deactivated = []

    async def check_cooldown(self, umo):
        return self.remaining

    async def activate(self, umo):
        self.activated.append(umo)
        return self.activate_result

    async def deactivate(self, umo):
        self.deactivated.append(umo)
        return True


class MessageHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_consumes_event_and_suppresses_default_llm(self):
        mod = _load_module()
        plugin = object.__new__(mod.ImmersiveControlPlugin)
        plugin.cfg = types.SimpleNamespace(
            admin_only_mode=False,
            enter_keywords={"进入"},
            exit_keywords={"退出"},
        )
        plugin.store = _Store()
        event = _Event("进入")

        async for _ in plugin.message_handler(event):
            pass

        self.assertTrue(event.call_llm)
        self.assertTrue(event.stopped)
        self.assertEqual(plugin.store.activated, [event.unified_msg_origin])

    async def test_exit_consumes_event_and_suppresses_default_llm(self):
        mod = _load_module()
        plugin = object.__new__(mod.ImmersiveControlPlugin)
        plugin.cfg = types.SimpleNamespace(
            admin_only_mode=False,
            enter_keywords={"进入"},
            exit_keywords={"退出"},
        )
        plugin.store = _Store()
        event = _Event("退出")

        async for _ in plugin.message_handler(event):
            pass

        self.assertTrue(event.call_llm)
        self.assertTrue(event.stopped)
        self.assertEqual(plugin.store.deactivated, [event.unified_msg_origin])

    async def test_cooldown_failure_also_consumes_event(self):
        mod = _load_module()
        plugin = object.__new__(mod.ImmersiveControlPlugin)
        plugin.cfg = types.SimpleNamespace(
            admin_only_mode=False,
            enter_keywords={"进入"},
            exit_keywords={"退出"},
        )
        plugin.store = _Store(remaining=5)
        event = _Event("进入")

        results = [result async for result in plugin.message_handler(event)]

        self.assertTrue(event.call_llm)
        self.assertTrue(event.stopped)
        self.assertEqual(results, ["还在休息中，请等待 5 秒"])
