# AstrBot 沉浸式互动控制插件

💗“我真的要控制你了”💗

🎮 给AI植入神奇小玩具的娱乐插件！一键"遥控"让AI瞬间害羞结巴，3分钟沉浸式互动体验～

## ✨ 插件简介

这是一个专为 AstrBot 设计的超有趣娱乐插件！通过简单的指令，你可以给AI"植入"各种可爱的小玩具，然后通过@机器人的方式来"遥控"它们。看着AI变得害羞、结巴、敏感，体验前所未有的互动乐趣！

### 🎯 主要特色

- 🎮 **一键触发**：@机器人 + 关键词即可开始3分钟沉浸式体验
- 🔧 **高度可配置**：自定义装置名称、敏感度、持续时间等所有参数
- 🛡️ **安全可控**：支持权限管理、冷却时间、并发限制
- 🎨 **自然反应**：基于AI的自然语言生成，无预制模板回复
- 🌐 **WebUI管理**：可视化配置界面，操作简单直观
- 📊 **状态监控**：实时查看控制状态、管理员命令丰富

## 🚀 快速开始

### 安装方式

1. **直接下载**：将整个仓库下载到 AstrBot 的 `data/plugins/` 目录下
2. **Git克隆**：
   ```bash
   cd /path/to/astrbot/data/plugins/
   git clone https://github.com/muyouzhi6/astrbot_plugin_immersive_control.git
   ```

### 基本使用

1. 重启 AstrBot 自动加载插件
2. 在群聊中 @机器人 + 以下任一关键词：
   - `控制`
   - `我要控制你了`
   - `启动玩具`
   - `遥控`
   - `td`
3. 享受3分钟的沉浸式互动体验！

## ⚙️ 配置说明

插件会自动生成配置文件：`data/config/immersive_control.yaml`

```yaml
# 是否启用插件
enabled: true

# 触发关键词列表
trigger_keywords:
  - "我要控制你了"
  - "控制"
  - "启动玩具"
  - "遥控"
  - "td"

# 小玩具名称（可自定义任何名称）
interactive_item_name: "特殊装置"

# 控制持续时间（秒）
state_duration_seconds: 180

# 敏感度等级 (0-100)
sensitivity_level: 50

# 最大并发控制数量
max_concurrent_states: 10

# 冷却时间（秒）
cooldown_seconds: 30

# 是否仅管理员可用
admin_only_mode: false

# 授权用户列表（空则所有人可用）
authorized_users: []

# 日志等级
log_level: "INFO"
```

## 🎮 管理员命令

插件提供了丰富的管理员命令：

- `/imm_status` - 查看当前所有控制状态
- `/imm_clear` - 清除所有控制状态
- `/imm_reload` - 重新加载配置文件
- `/imm_enable` - 启用插件
- `/imm_disable` - 禁用插件
- `/imm_add_user <用户ID>` - 添加授权用户
- `/imm_remove_user <用户ID>` - 移除授权用户
- `/imm_list_users` - 查看授权用户列表
- `/imm_info` - 查看插件详细信息

## 🌐 WebUI 配置

插件支持通过 AstrBot 的 WebUI 进行可视化配置：

1. 访问 AstrBot WebUI（默认：http://localhost:6185）
2. 登录后进入插件管理页面
3. 找到"沉浸式互动控制"插件
4. 点击配置按钮进行可视化设置

## 🔧 高级功能

### 自定义装置名称

可以将 `interactive_item_name` 设置为任何你想要的名称，AI会根据这个名称自然生成对应的反应。

### 权限管理

- `admin_only_mode: true` - 仅管理员可使用
- `authorized_users` - 指定授权用户列表

### 安全控制

- 冷却时间避免频繁触发
- 并发限制防止资源滥用
- 状态自动过期机制

## 📝 开发说明

### 项目结构

```
astrbot_plugin_immersive_control/
├── main.py                 # 插件主程序
├── metadata.yaml          # 插件元数据
├── _conf_schema.json      # WebUI配置界面定义
├── README.md              # 说明文档
└── __init__.py            # Python包初始化
```

### 核心类

- `ConfigurationManager` - 配置管理器
- `StateManager` - 状态管理器  
- `Main` - 插件主类

### 关键功能

- `before_llm_request` - LLM请求前的Prompt注入
- `immersive_control_handler` - 消息处理器
- 各种管理员命令处理函数

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境

1. 确保有完整的 AstrBot 开发环境
2. Python 3.10+
3. 了解 AstrBot 插件开发规范

### 提交规范

- 代码需要通过 ruff 格式化
- 提交信息请使用中文
- 新功能需要更新文档

## 📄 许可证

本项目使用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- 感谢 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 提供的优秀插件框架
- 感谢所有测试用户的反馈和建议

## ⚠️ 免责声明

本插件纯属娱乐性质，请合理使用。作者不对使用本插件产生的任何后果负责。

---

**作者**: 木有知  
**版本**: 1.0.0  
**仓库**: https://github.com/muyouzhi6/astrbot_plugin_immersive_control
