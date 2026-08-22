<div align="center">

# 🤖 kurigram-mcp

**用 AI 调试 Telegram bot** — 通过 Telegram 用户会话 (MTProto) 驱动 AI 的本地 MCP 服务器。

[![PyPI Version](https://img.shields.io/pypi/v/kurigram-mcp.svg)](https://pypi.org/project/kurigram-mcp/)
[![Python Versions](https://img.shields.io/pypi/pyversions/kurigram-mcp.svg)](https://pypi.org/project/kurigram-mcp/)
[![License](https://img.shields.io/pypi/l/kurigram-mcp.svg)](https://github.com/z-mio/kurigram-mcp/blob/main/LICENSE)

[English](README.md) · **简体中文**

</div>

---

## ✨ 特性

|                   |                                                                                           |
|-------------------|-------------------------------------------------------------------------------------------|
| 🔌 **标准 MCP**   | Streamable HTTP 传输,2026-07-28 协议,向下兼容 2025-11-25 客户端 (Claude Code、Codex、DSH) |
| 🧪 **Bot 调试**   | 发送 `/start`、测量回复延迟、等待事件、消费更新流                                         |
| 🛠️ **深度调试**   | `raw_invoke` 调用任意 MTProto 函数,内置 API 发现                                          |
| 🔒 **聊天白名单** | 账号级白名单 + 全局兜底,fail-closed                                                       |
| ⚡ **无状态**     | 服务器重启不影响已连接的客户端                                                            |
| 🚀 **零配置**     | `uv tool install` + 交互式向导,一条命令登录                                               |

## 🚀 快速开始

```bash
# 1. 安装(提供 kurigram-mcp 与 km 两个命令)
uv tool install kurigram-mcp

# 2. 一次性配置:API_ID / API_HASH / 白名单 / 代理
#    AUTH_TOKEN 自动生成(Bearer 鉴权默认开启)
km setup

# 3. 登录
km session add          # 交互向导:账号名 → 凭据 → 白名单 → 手机号 → 验证码 → 2FA

# 4. 启动服务器
km run     # 默认 http://127.0.0.1:8765/mcp

# 5. 总览与生效
km status               # 服务器状态 + 账号表,一眼看完
km restart              # 重启运行中的服务器(账号/白名单改动后生效)
```

> 在 [my.telegram.org/apps](https://my.telegram.org/apps) 获取 `API_ID` / `API_HASH`。登录必须由你本人完成——凭据永远不会离开你的机器。

## 👥 多账号会话

有些测试场景需要多个用户同时参与 (比如群内 bot 的多人交互)。每个 Telegram 用户注册一个账号,
各账号拥有独立的会话文件、可选代理与聊天白名单 —— **所有账号在一个服务器里,每个工具带
`account` 参数**:

```bash
# 1. 逐个添加账号
km session add alice    # 交互向导;凭据默认复用 setup 的应用,回车即过
km session add bob

# 2. 查看登录状态
km session list          # 加 -v 显示 proxy/白名单详情

# 3. 修改账号的白名单/代理
km session set alice --allowed-chat-ids="-1001234567890,@mybot,me"   # 注意:负号开头的值用 `=` 传参
km session set alice --allowed-chat-ids ""   # 清空 → 回退全局白名单
km session set bob --proxy socks5://127.0.0.1:1080   # 或 --proxy "" 清除

# 4. 只启动一个服务器 —— 所有已登录账号一起连上
km run                   # 之后每个工具都可传 account="alice" / account="bob"
```

- 所有工具 (发送/读取/事件/raw/`whoami`)都接受 `account: <名字>` 参数;省略则用默认账号。 例:
  `send_message(account="alice")` → `wait_for_update(account="alice")` 接龙编排多用户场景。
- `km run --account alice` 可启动单账号服务器 (隔离模式)。
- 旧式单账号配置 (顶层 `api_id`)即隐式账号 **`default`**。
- 每账号 `--allowed-chat-ids` 覆盖全局白名单;未设置的账号回退全局 `allowed_chat_ids`。
- `mcp_get_server_info` 列出所有已连接账号。

## 🧰 工具 (34 个)

| 分组    | 工具                                                                                                                                                                                                                                                                         |
|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 🧾 会话 | `whoami`、`mcp_get_server_info`                                                                                                                                                                                                                                              |
| 📤 发送 | `send_message`、`send_photo`、`send_document`、`send_voice`、`send_sticker`、`send_media_group`、`send_poll`、`vote_poll`、`forward_message`、`edit_message`、`delete_message`、`send_chat_action`、`start_bot`、`click_inline_button`、`send_reaction`、`send_inline_query` |
| 📥 读取 | `get_chat`、`get_chat_history`、`get_messages`、`get_dialogs`、`search_messages`、`get_chat_members_count`、`download_media`                                                                                                                                                 |
| 👥 群   | `join_chat`、`leave_chat`                                                                                                                                                                                                                                                    |
| ⏱️  事件 | `wait_for_update`(谓词含 `is_media` / `media_type`)、`drain_updates`                                                                                                                                                                                                         |
| 🔬 深度 | `raw_invoke`、`list_raw_methods`、`get_raw_method_info`                                                                                                                                                                                                                      |

## 🔌 客户端接入

```bash
# Claude Code
claude mcp add --transport http kurigram-mcp http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer <AUTH_TOKEN>"
```

```toml
# Codex (~/.codex/config.toml)
[mcp_servers.kurigram-mcp]
url = "http://127.0.0.1:8765/mcp"
http_headers = { "Authorization" = "Bearer <AUTH_TOKEN>" }
```

```yaml
# DSH — cordis.yml 插件行(@deepseek-ai/dsh-mcp-client)
- id: mcp-kurigram
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: kurigram
    transport: streamable-http
    url: http://127.0.0.1:8765/mcp
    headers:
      Authorization: !!js '`Bearer ${process.env.KURIGRAM_TOKEN}`'
```

### 🔐 聊天白名单

1. **账号级白名单** — `km session add NAME --allowed-chat-ids "..."`(逗号分隔:数字 chat_id、`@username`、`me`), 每账号互相隔离。
2. **全局兜底** — 配置 `allowed_chat_ids` 作用于未设置账号级白名单的账号。

## ⚙️ 配置

所有配置只在一个文件:`~/.kurigram-mcp/config.yaml`。

```yaml
api_id: 123456
api_hash: your_hash
allowed_chat_ids: "123456789,me"   # 兜底白名单
host: 127.0.0.1
port: 8765
auth_token: auto_generated_or_yours # Bearer 鉴权
proxy: ""                           # 可选,如 socks5://127.0.0.1:1080
```

## 📁 数据与文件

```
~/.kurigram-mcp/
├── config.yaml         # setup 生成的配置(权限 600)
├── sessions/           # Telegram 会话文件:u_{API_ID}.session(每账号一个)
└── downloads/          # download_media 落盘目录
```

## 🧑‍💻 开发

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts

# 与用户一致的方式配置(共享 ~/.kurigram-mcp):
uv run kurigram-mcp setup
# 或隔离开发环境(不碰真实配置):
# KURIGRAM_MCP_HOME=$PWD/.dev-home uv run kurigram-mcp setup
# KURIGRAM_MCP_HOME=$PWD/.dev-home uv run kurigram-mcp run
```

## 📄 License

[MIT](LICENSE)
