"""
AstrBot 沉浸式互动控制插件

此插件允许用户通过自然语言关键词触发机器人进入特殊的"被控制"状态，
通过动态Prompt注入来实现沉浸式的角色扮演互动体验。

核心功能：
1. 自然语言触发器系统
2. 动态Prompt注入与状态管理
3. 用户自定义配置支持
4. 完整的日志记录和错误处理
5. 并发安全与数据持久化

Author: 木有知
Version: 2.1.0
Compatible with: AstrBot v4.12.3+
"""

from .main import Main

__version__ = "2.1.0"
__author__ = "木有知"
__description__ = "AstrBot沉浸式互动控制插件 - 通过自然语言触发的角色扮演系统"
