from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star import Star
from astrbot.core.star.context import Context

from .core.config import PluginConfig
from .core.data import SessionStore


class ImmersiveControlPlugin(Star):
    """沉浸式控制插件"""
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config, context)
        self.store = SessionStore(self.cfg)

    # ========== 生命周期 ==========
    async def initialize(self):
        logger.info("沉浸式控制插件已初始化")

    async def terminate(self):
        logger.info("沉浸式控制插件已卸载")

    @staticmethod
    def safe_format(template: str, **kwargs) -> str:
        """安全的模板格式化，防止 KeyError"""
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"模板格式化失败，缺少变量: {e}")
            return template
        except Exception as e:
            logger.error(f"模板格式化异常: {e}")
            return template

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        umo = event.unified_msg_origin
        record = await self.store.get(umo)
        if not record:
            return
        # ACTIVE：注入控制提示
        if record.is_active:
            prompt = self.safe_format(
                self.cfg.system_prompt_template,
                item_name=record.item_name,
                sensitivity=record.sensitivity or self.cfg.sensitivity_level,
            )
            req.system_prompt += f"\n\n{prompt}"
        # EXIT_PENDING：注入退出提示
        else:
            exit_record = await self.store.complete_exit(umo)
            if exit_record:
                prompt = self.safe_format(
                    self.cfg.exit_notice_template,
                    item_name=exit_record.item_name,
                )
                req.system_prompt += f"\n\n{prompt}"

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def message_handler(self, event: AstrMessageEvent):
        # 权限
        if self.cfg.admin_only_mode and not event.is_admin():
            return
        # 指令
        if not event.message_str:
            return
        cmd = event.message_str.partition(" ")[0]
        umo = event.unified_msg_origin
        # 退出
        if cmd in self.cfg.exit_keywords:
            await self.store.deactivate(umo)
            logger.info(f"{umo} 沉浸状态已退出")
            return
        # 进入
        if cmd not in self.cfg.trigger_keywords:
            return

        # 冷却
        remaining = await self.store.check_cooldown(umo)
        if remaining > 0:
            yield event.plain_result(f"还在休息中，请等待 {remaining} 秒")
            return

        # 激活
        ok, msg = await self.store.activate(umo)
        if ok:
            logger.debug(f"{umo} 沉浸状态已激活")
            return
        yield event.plain_result(msg)

    @filter.command("imm_stop")
    async def stop_command(self, event: AstrMessageEvent):
        ok = await self.store.deactivate(event.unified_msg_origin)
        yield event.plain_result("已退出沉浸模式" if ok else "当前未处于沉浸状态")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("imm_status")
    async def status_command(self, event: AstrMessageEvent):
        states = await self.store._load_states()
        states, changed = self.store._cleanup_states(states)
        if changed:
            await self.store._save_states(states)
        active = sum(1 for s in states.values() if s.is_active)
        pending = sum(1 for s in states.values() if not s.is_active)

        msg = [
            "=== 沉浸式控制插件状态 ===",
            f"激活中: {active}",
            f"等待退出: {pending}",
            f"最大并发: {self.cfg.max_concurrent_states}",
            f"持续时间: {self.cfg.state_duration_seconds}s",
            f"冷却时间: {self.cfg.cooldown_seconds}s",
        ]

        yield event.plain_result("\n".join(msg))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("imm_clear")
    async def clear_command(self, event: AstrMessageEvent):
        await self.put_kv_data(SessionStore.KV_STATES, {})
        await self.put_kv_data(SessionStore.KV_COOLDOWNS, {})
        yield event.plain_result("已清空所有沉浸状态和冷却数据")
