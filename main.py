import time

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
        self.cfg = PluginConfig(config)
        self.store = SessionStore(self.cfg)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        umo = event.unified_msg_origin
        record = await self.store.get(umo)
        if not record:
            return
        # 激活态：持续注入
        if record.active:
            template = self.cfg.enter_template
        # 退出态：只注入一次
        elif record.exit_ts is not None:
            template = self.cfg.exit_template
            await self.store.complete_exit(umo)
        else:
            return
        prompt = template
        prompt = prompt.replace("{item_name}", str(self.cfg.item_name))
        prompt = prompt.replace("{sensitivity}", str(self.cfg.sensitivity))

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
        if cmd not in self.cfg.enter_keywords:
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("imm_status", alias={"控制状态"})
    async def status_command(self, event: AstrMessageEvent):
        umo = event.unified_msg_origin
        record = await self.store.get(umo)
        if not record:
            return

        now = time.time()
        msg: list[str] = []

        # 状态
        msg.append(f"控制状态: {'激活中' if record.active else '未激活'}")

        # 激活态
        if record.active and record.end is not None:
            remain = max(0, int(record.end - now))
            msg.append(f"剩余时间: {remain}秒")

        # 退出中
        elif record.exit_ts is not None:
            msg.append(f"退出原因: {record.reason or 'unknown'}")

        # 冷却
        cooldown = max(0, int(record.cooldown_end - now))
        if cooldown > 0:
            msg.append(f"冷却剩余: {cooldown}秒")

        yield event.plain_result("\n".join(msg))
