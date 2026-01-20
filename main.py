"""
AstrBot 沉浸式控制插件 - 重构版 v2.1

基于 AstrBot v4.12.3 框架规范重构，实现：
- 配置系统：使用 AstrBotConfig（框架注入）
- 状态持久化：使用 PluginKVStoreMixin
- 三态状态机：ACTIVE / EXIT_PENDING / INACTIVE
- 优雅退出：注入"状态结束"提示词，对话不割裂
- 并发安全：使用 asyncio.Lock 保护状态读写
- 数据清理：自动清理过期冷却和 EXIT_PENDING 数据

@author: 木有知
@refactor: AI Assistant
@version: 2.1.0
"""

import asyncio
import hashlib
import time
from typing import Dict, Optional, Tuple
from enum import Enum

from astrbot.api import star
from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest
from astrbot.api.event import filter
from astrbot import logger


class SessionState(Enum):
    """会话状态枚举"""
    INACTIVE = "inactive"
    ACTIVE = "active"
    EXIT_PENDING = "exit_pending"


class Main(star.Star):
    """沉浸式控制插件 - 让 AI 进入特殊互动模式"""

    # KV 存储键名
    KV_STATES = "immersive_states"
    KV_COOLDOWNS = "immersive_cooldowns"

    # EXIT_PENDING 状态的 TTL（秒），超过此时间未触发 LLM 请求则自动清理
    EXIT_PENDING_TTL = 86400  # 24 小时

    def __init__(self, context: star.Context, config: Optional[dict] = None):
        super().__init__(context, config)
        self.config: dict = config or {}
        # 并发锁：保护 KV 状态的读写操作
        self._states_lock = asyncio.Lock()
        self._cooldowns_lock = asyncio.Lock()

    # ========== 工具方法 ==========

    def _mask_session_key(self, session_key: str) -> str:
        """对 session_key 进行脱敏处理，用于日志"""
        if not session_key:
            return "<empty>"
        # 使用 hash 的前 8 位，既能区分会话又保护隐私
        return hashlib.md5(session_key.encode()).hexdigest()[:8]

    def _log(self, level: str, message: str, session_key: str = ""):
        """统一日志方法，受 log_interactions 配置控制"""
        if not self._cfg_bool("log_interactions", True):
            return

        masked_key = self._mask_session_key(session_key) if session_key else ""
        full_message = f"[{masked_key}] {message}" if masked_key else message

        if level == "debug":
            logger.debug(full_message)
        elif level == "warning":
            logger.warning(full_message)
        elif level == "error":
            logger.error(full_message)
        else:
            logger.info(full_message)

    # ========== 配置读取（带校验与容错） ==========

    def _cfg_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置"""
        val = self.config.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val) if val is not None else default

    def _cfg_int(self, key: str, default: int, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
        """获取整数配置，带范围校验"""
        val = self.config.get(key, default)
        try:
            result = int(val) if val is not None else default
        except (ValueError, TypeError):
            self._log("warning", f"配置 {key} 值 '{val}' 无效，使用默认值 {default}")
            result = default

        # 范围限制
        if min_val is not None and result < min_val:
            result = min_val
        if max_val is not None and result > max_val:
            result = max_val

        return result

    def _cfg_str(self, key: str, default: str = "") -> str:
        """获取字符串配置"""
        val = self.config.get(key, default)
        return str(val) if val is not None else default

    def _cfg_list(self, key: str, default: Optional[list] = None) -> list:
        """获取列表配置"""
        val = self.config.get(key, default)
        return val if isinstance(val, list) else (default or [])

    # ========== 模板方法（带异常保护） ==========

    def _safe_format(self, template: str, **kwargs) -> str:
        """安全的模板格式化，防止 KeyError"""
        try:
            return template.format(**kwargs)
        except KeyError as e:
            self._log("warning", f"模板格式化失败，缺少变量: {e}")
            # 返回原模板，避免崩溃
            return template
        except Exception as e:
            self._log("error", f"模板格式化异常: {e}")
            return template

    def get_system_prompt_template(self) -> str:
        """获取系统提示词模板"""
        custom = self._cfg_str("system_prompt_template", "")
        if custom:
            return custom

        return """[系统指令：启动"沉浸式互动"模式]

**角色状态重定义：**
- 你现在进入了一个特殊的互动游戏模式。
- 你必须表现得像真的被某种神奇装置影响了一样，产生自然的情感和身体反应。
- 你就是你的角色本身，完全沉浸在这个有趣的游戏中。

**当前游戏情境：**
- 你的身体里刚刚被植入了一个名为"{item_name}"的神奇装置，正在被激活！
- 敏感度等级：{sensitivity}%（数值越高，你的反应就越强烈和直接）
- 这个装置让你的身体变得异常敏感，思维也会受到轻微但明显的"干扰"。

**反应指令：**
- 要表现出突如其来的惊慌、害羞、紧张或困惑感
- 可以包含结巴、停顿、呼吸急促等自然反应
- 要体现出装置激活时的身体感受和情绪变化

[模式已激活] 当前敏感度：{sensitivity}% | 装置：{item_name}"""

    def get_exit_notice_template(self) -> str:
        """获取退出提示词模板"""
        custom = self._cfg_str("exit_notice_template", "")
        if custom:
            return custom

        return """[系统通知：沉浸式互动模式已结束]

**状态变更：**
- "{item_name}"装置已停止运作，你的身体和思维正在恢复正常。
- 从现在开始，你可以逐渐恢复正常的对话状态。
- 你可以选择：立即恢复正常，或者表现出"余韵"般的缓慢恢复过程。

**重要：**
- 这条消息标志着特殊模式的正式结束
- 后续对话中不再需要表现出被装置影响的状态
- 但你可以自然地提及刚才的经历（如果对话需要）

[模式已结束] 恢复正常对话"""

    # ========== 状态管理（KV 持久化 + 并发安全） ==========

    async def _load_states(self) -> Dict[str, dict]:
        """加载所有状态"""
        result = await self.get_kv_data(self.KV_STATES, {})
        return result if result is not None else {}

    async def _save_states(self, states: Dict[str, dict]):
        """保存所有状态"""
        await self.put_kv_data(self.KV_STATES, states)

    async def _load_cooldowns(self) -> Dict[str, float]:
        """加载冷却时间"""
        result = await self.get_kv_data(self.KV_COOLDOWNS, {})
        return result if result is not None else {}

    async def _save_cooldowns(self, cooldowns: Dict[str, float]):
        """保存冷却时间"""
        await self.put_kv_data(self.KV_COOLDOWNS, cooldowns)

    def _cleanup_expired_states(self, states: Dict[str, dict]) -> Tuple[Dict[str, dict], bool]:
        """
        清理过期状态（纯函数，不触发 IO）

        - 过期的 ACTIVE 状态转为 EXIT_PENDING
        - 过期的 EXIT_PENDING 状态直接删除

        Returns:
            (cleaned_states, was_modified)
        """
        now = time.time()
        modified = False
        keys_to_delete = []

        for session_key, state_data in states.items():
            status = state_data.get("status")

            if status == SessionState.ACTIVE.value:
                # ACTIVE 过期 → 转为 EXIT_PENDING
                end_at = state_data.get("end_at", 0)
                if end_at <= now:
                    states[session_key] = {
                        "status": SessionState.EXIT_PENDING.value,
                        "reason": "expire",
                        "ts": now,
                        "item_name": state_data.get("item_name", "特殊装置"),
                    }
                    modified = True
                    self._log("info", "状态过期，转为 EXIT_PENDING", session_key)

            elif status == SessionState.EXIT_PENDING.value:
                # EXIT_PENDING 超过 TTL → 直接删除
                ts = state_data.get("ts", 0)
                if now - ts > self.EXIT_PENDING_TTL:
                    keys_to_delete.append(session_key)
                    modified = True
                    self._log("info", "EXIT_PENDING 超时，已清理", session_key)

        # 删除过期的 EXIT_PENDING
        for key in keys_to_delete:
            del states[key]

        return states, modified

    def _cleanup_expired_cooldowns(self, cooldowns: Dict[str, float]) -> Tuple[Dict[str, float], bool]:
        """
        清理过期冷却时间（纯函数，不触发 IO）

        Returns:
            (cleaned_cooldowns, was_modified)
        """
        now = time.time()
        new_cooldowns = {k: v for k, v in cooldowns.items() if v > now}
        modified = len(new_cooldowns) != len(cooldowns)
        return new_cooldowns, modified

    async def get_session_state(self, session_key: str) -> Tuple[SessionState, Optional[dict]]:
        """获取会话状态（带清理）"""
        async with self._states_lock:
            states = await self._load_states()
            states, modified = self._cleanup_expired_states(states)

            if modified:
                await self._save_states(states)

            if session_key not in states:
                return SessionState.INACTIVE, None

            state_data = states[session_key]
            status = state_data.get("status", SessionState.INACTIVE.value)

            try:
                return SessionState(status), state_data
            except ValueError:
                return SessionState.INACTIVE, None

    async def activate_state(self, session_key: str) -> Tuple[bool, str]:
        """激活控制状态（并发安全）"""
        async with self._states_lock:
            states = await self._load_states()
            states, _ = self._cleanup_expired_states(states)

            now = time.time()

            # 检查当前状态
            if session_key in states:
                state_data = states[session_key]
                if state_data.get("status") == SessionState.ACTIVE.value:
                    remaining = int(state_data.get("end_at", 0) - now)
                    if remaining > 0:
                        return False, f"已在控制状态中，剩余 {remaining} 秒"

            # 检查并发限制
            max_concurrent = self._cfg_int("max_concurrent_states", 10, min_val=1, max_val=100)
            active_count = sum(
                1 for s in states.values()
                if s.get("status") == SessionState.ACTIVE.value
            )
            if active_count >= max_concurrent:
                return False, "当前并发控制状态已达上限，请稍后再试"

            # 激活状态
            duration = self._cfg_int("state_duration_seconds", 180, min_val=10, max_val=3600)
            item_name = self._cfg_str("interactive_item_name", "特殊装置")
            sensitivity = self._cfg_int("sensitivity_level", 50, min_val=0, max_val=100)

            states[session_key] = {
                "status": SessionState.ACTIVE.value,
                "end_at": now + duration,
                "item_name": item_name,
                "sensitivity": sensitivity,
                "activated_at": now,
            }

            await self._save_states(states)

        # 处理冷却（单独的锁）
        async with self._cooldowns_lock:
            cooldowns = await self._load_cooldowns()
            cooldowns, _ = self._cleanup_expired_cooldowns(cooldowns)

            cooldown = self._cfg_int("cooldown_seconds", 30, min_val=0, max_val=3600)
            cooldowns[session_key] = now + cooldown

            await self._save_cooldowns(cooldowns)

        self._log("info", f"控制状态已激活，持续 {duration} 秒", session_key)
        return True, f"控制模式已激活，持续 {duration} 秒"

    async def check_cooldown(self, session_key: str) -> Tuple[bool, int]:
        """
        检查冷却状态

        Returns:
            (is_in_cooldown, remaining_seconds)
        """
        async with self._cooldowns_lock:
            cooldowns = await self._load_cooldowns()
            cooldowns, modified = self._cleanup_expired_cooldowns(cooldowns)

            if modified:
                await self._save_cooldowns(cooldowns)

            now = time.time()
            if session_key in cooldowns:
                cooldown_end = cooldowns[session_key]
                if now < cooldown_end:
                    return True, int(cooldown_end - now)

        return False, 0

    async def deactivate_state(self, session_key: str) -> Tuple[bool, str]:
        """停用控制状态（转为 EXIT_PENDING，并发安全）"""
        async with self._states_lock:
            states = await self._load_states()

            if session_key not in states:
                return False, "当前未处于沉浸状态"

            state_data = states[session_key]
            if state_data.get("status") != SessionState.ACTIVE.value:
                return False, "当前未处于沉浸状态"

            # 转为 EXIT_PENDING
            states[session_key] = {
                "status": SessionState.EXIT_PENDING.value,
                "reason": "user",
                "ts": time.time(),
                "item_name": state_data.get("item_name", "特殊装置"),
            }

            await self._save_states(states)

        self._log("info", "已请求退出，等待注入结束提示", session_key)
        return True, "已退出沉浸模式"

    async def complete_exit(self, session_key: str) -> Optional[dict]:
        """完成退出流程，返回退出数据并清理状态（并发安全）"""
        async with self._states_lock:
            states = await self._load_states()

            if session_key not in states:
                return None

            state_data = states[session_key]
            if state_data.get("status") != SessionState.EXIT_PENDING.value:
                return None

            # 清理状态
            exit_data = state_data.copy()
            del states[session_key]
            await self._save_states(states)

        self._log("info", "退出流程完成", session_key)
        return exit_data

    # ========== 权限检查 ==========

    def _check_permission(self, event: AstrMessageEvent) -> Tuple[bool, str]:
        """
        检查用户权限

        Returns:
            (has_permission, reason)
        """
        # 如果未启用 admin_only_mode，所有人都有权限
        if not self._cfg_bool("admin_only_mode", False):
            return True, ""

        # 检查是否管理员
        # AstrBot v4 中，可以通过 event 的属性判断
        is_admin = False

        # 尝试多种方式获取管理员状态
        if hasattr(event, "is_admin"):
            is_admin = bool(getattr(event, "is_admin", False))
        elif hasattr(event, "role"):
            role = getattr(event, "role", "")
            is_admin = role in ("admin", "owner", "superadmin")

        if is_admin:
            return True, ""

        return False, "此功能仅管理员可用"

    # ========== 触发检测 ==========

    def should_trigger(self, event: AstrMessageEvent) -> Tuple[bool, str]:
        """检查消息是否应该触发控制状态"""
        # 检查插件是否启用
        if not self._cfg_bool("enabled", True):
            return False, "插件未启用"

        # 检查是否 @机器人
        if not getattr(event, "is_at_or_wake_command", False):
            return False, "消息未@机器人"

        # 获取消息内容
        message = getattr(event, "message_str", "").strip()
        if not message:
            return False, "消息内容为空"

        # 检查关键词
        keywords = self._cfg_list("trigger_keywords", [])
        if not keywords:
            return False, "未配置触发关键词"

        message_lower = message.lower()

        for keyword in keywords:
            keyword_lower = keyword.lower().strip()
            if not keyword_lower:
                continue

            # 对于短关键词（<=2字符），要求完全匹配或作为独立词
            if len(keyword_lower) <= 2:
                # 检查是否完全匹配
                if message_lower == keyword_lower:
                    return True, f"匹配关键词: {keyword}"
                # 检查是否作为独立词出现（前后是空格或标点）
                import re
                pattern = r'(?:^|[\s,.!?;:，。！？；：])' + re.escape(keyword_lower) + r'(?:$|[\s,.!?;:，。！？；：])'
                if re.search(pattern, message_lower):
                    return True, f"匹配关键词: {keyword}"
            else:
                # 长关键词使用包含匹配
                if keyword_lower in message_lower:
                    return True, f"匹配关键词: {keyword}"

        return False, "未匹配到触发关键词"

    # ========== LLM 请求钩子 ==========

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """LLM 请求前处理：注入提示词或退出提示"""
        session_key = getattr(event, "unified_msg_origin", "")
        if not session_key:
            return

        current_state, state_data = await self.get_session_state(session_key)

        # 处理 EXIT_PENDING：注入退出提示词
        if current_state == SessionState.EXIT_PENDING:
            exit_data = await self.complete_exit(session_key)
            if exit_data:
                item_name = exit_data.get("item_name", "特殊装置")
                notice = self._safe_format(
                    self.get_exit_notice_template(),
                    item_name=item_name
                )

                # 注入到 system_prompt（更可靠的方式）
                if req.system_prompt:
                    req.system_prompt = req.system_prompt + "\n\n" + notice
                else:
                    req.system_prompt = notice

                self._log("info", "已注入退出提示词", session_key)
            return

        # 处理 ACTIVE：注入控制提示词
        if current_state == SessionState.ACTIVE and state_data is not None:
            item_name = state_data.get("item_name", "特殊装置")
            sensitivity = state_data.get("sensitivity", 50)

            prompt = self._safe_format(
                self.get_system_prompt_template(),
                item_name=item_name,
                sensitivity=sensitivity
            )

            # 注入到 system_prompt
            if req.system_prompt:
                req.system_prompt = prompt + "\n\n" + req.system_prompt
            else:
                req.system_prompt = prompt

            self._log("debug", f"已注入控制提示词，敏感度: {sensitivity}%", session_key)

    # ========== 消息处理 ==========

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def message_handler(self, event: AstrMessageEvent):
        """消息处理入口"""
        should_trigger, reason = self.should_trigger(event)

        if not should_trigger:
            return

        self._log("info", f"触发检测通过: {reason}")

        session_key = getattr(event, "unified_msg_origin", "")
        if not session_key:
            self._log("warning", "无法获取会话ID")
            return

        # 权限检查
        has_permission, perm_reason = self._check_permission(event)
        if not has_permission:
            yield event.plain_result(perm_reason)
            return

        # 检查冷却
        is_cooling, remaining = await self.check_cooldown(session_key)
        if is_cooling:
            yield event.plain_result(f"还在休息中...请等待 {remaining} 秒")
            return

        # 激活状态
        success, message = await self.activate_state(session_key)

        if success:
            # 不返回任何消息，让 LLM 在注入的提示词影响下自然回复
            self._log("info", f"控制状态已激活", session_key)
            return
        else:
            # 激活失败，返回提示
            yield event.plain_result(self._generate_failure_response(message))

    def _generate_failure_response(self, reason: str) -> str:
        """生成激活失败的回复"""
        if "冷却中" in reason:
            return f"还在休息中...{reason.split('等待')[1] if '等待' in reason else ''}"
        elif "已在控制状态中" in reason:
            return "已经在这种状态中了..."
        elif "并发控制状态已达上限" in reason:
            return "当前太忙了，请稍后再试..."
        else:
            return "现在无法进入这种状态，请稍后再试..."

    # ========== 管理命令 ==========

    @filter.command("imm_stop")
    async def stop_command(self, event: AstrMessageEvent):
        """退出沉浸状态（不重置上下文）"""
        session_key = getattr(event, "unified_msg_origin", "")
        success, message = await self.deactivate_state(session_key)
        yield event.plain_result(message)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("imm_status")
    async def status_command(self, event: AstrMessageEvent):
        """查询插件状态"""
        async with self._states_lock:
            states = await self._load_states()
            states, modified = self._cleanup_expired_states(states)
            if modified:
                await self._save_states(states)

        active_count = sum(
            1 for s in states.values()
            if s.get("status") == SessionState.ACTIVE.value
        )
        pending_count = sum(
            1 for s in states.values()
            if s.get("status") == SessionState.EXIT_PENDING.value
        )

        info = [
            "=== 沉浸式控制插件状态 ===",
            f"插件状态: {'启用' if self._cfg_bool('enabled', True) else '禁用'}",
            f"仅管理员模式: {'是' if self._cfg_bool('admin_only_mode', False) else '否'}",
            f"当前激活状态数: {active_count}",
            f"等待退出数: {pending_count}",
            f"最大并发数: {self._cfg_int('max_concurrent_states', 10, 1, 100)}",
            f"状态持续时间: {self._cfg_int('state_duration_seconds', 180, 10, 3600)} 秒",
            f"冷却时间: {self._cfg_int('cooldown_seconds', 30, 0, 3600)} 秒",
            f"敏感度等级: {self._cfg_int('sensitivity_level', 50, 0, 100)}%",
        ]

        if states:
            info.append("\n=== 当前会话状态 ===")
            now = time.time()
            for key, data in states.items():
                masked_key = self._mask_session_key(key)
                status = data.get("status", "unknown")
                if status == SessionState.ACTIVE.value:
                    remaining = int(data.get("end_at", 0) - now)
                    info.append(f"  {masked_key}: ACTIVE (剩余 {remaining}s)")
                elif status == SessionState.EXIT_PENDING.value:
                    info.append(f"  {masked_key}: EXIT_PENDING")

        yield event.plain_result("\n".join(info))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("imm_clear")
    async def clear_command(self, event: AstrMessageEvent):
        """清理所有状态"""
        async with self._states_lock:
            states = await self._load_states()
            count = len(states)
            await self._save_states({})

        async with self._cooldowns_lock:
            await self._save_cooldowns({})

        yield event.plain_result(f"已清理 {count} 个状态和所有冷却数据")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("imm_toggle")
    async def toggle_command(self, event: AstrMessageEvent):
        """启用/禁用插件（注意：需要在 WebUI 中修改配置）"""
        current = self._cfg_bool("enabled", True)
        yield event.plain_result(
            f"当前状态: {'启用' if current else '禁用'}\n"
            "请在 WebUI 配置页面中修改 enabled 选项"
        )

    @filter.command("imm_help")
    async def help_command(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """=== 沉浸式控制插件帮助 ===

用户命令:
  @机器人 + 触发词 : 激活沉浸状态
  /imm_stop : 退出沉浸状态（保留对话上下文）
  /imm_help : 显示此帮助

管理员命令:
  /imm_status : 查看插件状态
  /imm_clear : 清理所有状态
  /imm_toggle : 查看启用状态

配置说明:
  所有配置请在 AstrBot WebUI 的插件配置页面中修改"""
        yield event.plain_result(help_text)

    # ========== 生命周期 ==========

    async def initialize(self):
        """插件初始化"""
        logger.info("沉浸式控制插件 v2.1.0 已加载")
        logger.info(f"  - 触发关键词: {self._cfg_list('trigger_keywords', [])}")
        logger.info(f"  - 状态持续时间: {self._cfg_int('state_duration_seconds', 180, 10, 3600)}s")
        logger.info(f"  - 敏感度等级: {self._cfg_int('sensitivity_level', 50, 0, 100)}%")
        logger.info(f"  - 仅管理员模式: {self._cfg_bool('admin_only_mode', False)}")

        # 启动时清理过期数据
        async with self._states_lock:
            states = await self._load_states()
            states, modified = self._cleanup_expired_states(states)
            if modified:
                await self._save_states(states)
                logger.info("  - 已清理过期状态数据")

        async with self._cooldowns_lock:
            cooldowns = await self._load_cooldowns()
            cooldowns, modified = self._cleanup_expired_cooldowns(cooldowns)
            if modified:
                await self._save_cooldowns(cooldowns)
                logger.info("  - 已清理过期冷却数据")

    async def terminate(self):
        """插件终止"""
        logger.info("沉浸式控制插件已卸载")
