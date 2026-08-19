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
| 🔒 **聊天白名单** | 请求头 per-client 声明,fail-closed                                                        |
| ⚡ **无状态**     | 服务器重启不影响已连接的客户端                                                            |
| 🚀 **零配置**     | `uv tool install` + 交互式向导,一条命令登录                                               |

## 🚀 快速开始

```bash
# 1. 安装(提供 kurigram-mcp 与 km 两个命令)
uv tool install kurigram-mcp

# 2. 一次性配置:API_ID / API_HASH / 白名单 / 代理 / 端口
#    AUTH_TOKEN 留空会自动生成(Bearer 鉴权默认开启)
km setup

# 3. 登录(setup 中已登录可跳过):手机号 → 验证码 → 2FA
km auth

# 4. 启动服务器
km run     # 默认 http://127.0.0.1:8765/mcp
```

> 在 [my.telegram.org/apps](https://my.telegram.org/apps) 获取 `API_ID` / `API_HASH`。登录必须由你本人完成——凭据永远不会离开你的机器。

## 🧰 工具 (22 个)

| 分组    | 工具                                                                                                                                                     |
|---------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| 🧾 会话 | `whoami`、`mcp_get_server_info`                                                                                                                          |
| 📤 发送 | `send_message`、`send_photo`、`send_document`、`edit_message`、`delete_message`、`send_chat_action`、`start_bot`、`click_inline_button`、`send_reaction` |
| 📥 读取 | `get_chat`、`get_chat_history`、`get_messages`、`get_dialogs`、`search_messages`、`download_media`                                                       |
| ⏱️  事件 | `wait_for_update`、`drain_updates`                                                                                                                       |
| 🔬 深度 | `raw_invoke`、`list_raw_methods`、`get_raw_method_info`                                                                                                  |

错误统一为 `[CODE] message` 格式:`NOT_WHITELISTED` · `FLOOD_WAIT {seconds}` · `SESSION_INVALID` · `RPC` · `NETWORK` ·
`INTERNAL`。

## 🔌 客户端接入

```bash
# Claude Code
claude mcp add --transport http kurigram-mcp http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer <AUTH_TOKEN>" \
  --header "X-Kurigram-Allowed-Chats: 6540476263"   # 可选:per-client 白名单
```

```toml
# Codex (~/.codex/config.toml)
[mcp_servers.kurigram-mcp]
url = "http://127.0.0.1:8765/mcp"
http_headers = { "Authorization" = "Bearer <AUTH_TOKEN>", "X-Kurigram-Allowed-Chats" = "6540476263" }
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
      X-Kurigram-Allowed-Chats: '6540476263'
```

### 🔐 聊天白名单

1. **请求头 `X-Kurigram-Allowed-Chats`** — per-client 声明 (逗号分隔:数字 chat_id、`@username`、`me`)。
2. **配置 `allowed_chat_ids`** — 请求头缺失时的兜底。

Fail-closed:白名单外的聊天一律拒绝,返回 `[NOT_WHITELISTED]`;`get_dialogs` 只返回白名单内的聊天。

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
├── u_{API_ID}.session  # Telegram 会话(与 API_ID 绑定,登录一次永久有效)
└── downloads/          # download_media 落盘目录
```

## 🧑‍💻 开发

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
```

## 📄 License

[MIT](LICENSE)
