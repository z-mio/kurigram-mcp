<div align="center">

# 🤖 kurigram-mcp

**用 AI 调试 Telegram bot** — 通过 Telegram 用户会话 (MTProto) 驱动的本地 MCP 服务器。

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
| ⚡ **无状态**     | 客户端在服务器重启后保持连接                                                              |
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

# 4. 启动服务器(前台运行,停止: Ctrl-C)
km run     # 默认 http://127.0.0.1:8765/mcp
```

> 在 [my.telegram.org/apps](https://my.telegram.org/apps) 获取 `API_ID` / `API_HASH`。登录必须由你本人完成——凭据只保存在你的机器上。

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
- 短参数:`km run -a/--account -H/--host -p/--port -u/--public-url -s/--stateful`;
  `km session add/set -x/--proxy -c/--allowed-chat-ids`;`km -V/--version`。

## 🧰 工具 (36 个)

| 分组    | 工具                                                                                                                                                                                                                                                                         |
|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 🧾 会话 | `whoami`、`mcp_get_server_info`                                                                                                                                                                                                                                              |
| 📤 发送 | `send_message`、`send_rich_message`、`send_photo`、`send_document`、`send_voice`、`send_sticker`、`send_media_group`、`send_poll`、`vote_poll`、`forward_message`、`edit_message`、`delete_message`、`send_chat_action`、`start_bot`、`click_inline_button`、`send_reaction`、`send_inline_query`、`create_upload_url` |
| 📥 读取 | `get_chat`、`get_chat_history`、`get_messages`、`get_dialogs`、`search_messages`、`get_chat_members_count`、`download_media`、`get_media_url`                                                                                                                               |
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

### 📁 远程文件传输

远程 MCP 客户端拿不到服务器本地文件,媒体传输走短时效签名 URL(presigned-URL 模式):

- **下载** — `get_media_url(chat_id, message_id)` 返回 `{url, file_name, mime_type, size_bytes}`;
  `curl -o <file_name> '<url>'` 即可经 HTTP 直接拉取(`GET /files/<chat>/<msg>`,支持 `Range` 断点续传)。
- **上传** — `create_upload_url(file_name)` 返回 `{url, media}`;`curl -T <本地文件> '<url>'` 把文件
  PUT 到按 uid 分桶的暂存目录,然后把 `media`(`upload://<uid>/<name>`)直接传给
  `send_photo` / `send_document` / `send_voice` / `send_sticker` / `send_media_group` / `send_rich_message`。

token 为进程内密钥签发的 HS256 JWT(重启后全部失效),绑定单一资源,`file_url_ttl_seconds`
到期失效(默认 900 秒)。上传 URL 单次有效;暂存文件超过 `upload_retention_hours`(默认 24 小时)后自动清理。

人工/脚本场景也可用主 `AUTH_TOKEN` —— 仅限 `Authorization: Bearer` 头(不能放 `?token=`):

```bash
curl -T a.png -H "Authorization: Bearer $AUTH_TOKEN" http://host:port/upload/a.png
curl -H "Authorization: Bearer $AUTH_TOKEN" -o x http://host:port/files/<chat_id>/<message_id>
```

> **外网访问地址(反代 / Cloudflare 隧道)**:从外网访问本服务时用 `-u, --public-url` 指定对外地址,
> 生成的上传/下载链接才会指向外网入口——反代会改写 `Host` 头,这正是服务器不从请求推导
> URL 的原因;仅在本机使用可不填:
>
> ```bash
> km run --public-url https://tg.example.com
> ```
>
> (也可用 `PUBLIC_BASE_URL` 环境变量或 config.yaml 的 `public_base_url`;命令行优先。)
> 注意 Cloudflare 代理对 Free/Pro 套餐的请求体上限为 100 MB:经隧道上传更大的文件会被
> Cloudflare 直接以 413 拒绝(下载不受影响)。

## ⚙️ 配置

所有配置只在一个文件:`~/.kurigram-mcp/config.yaml`。

```yaml
api_id: 123456
api_hash: your_hash
allowed_chat_ids: "123456789,me"   # 兜底白名单
host: 127.0.0.1
port: 8765
auth_token: auto_generated_or_yours # Bearer 鉴权
public_base_url: ""                 # 外网访问地址(如隧道域名);仅本机使用可不填,留空按 http://host:port 推导
file_url_ttl_seconds: 900           # 签名文件 URL 有效期
upload_max_bytes: 2147483648        # 单次上传上限(2 GiB)
upload_retention_hours: 24          # 上传暂存保留时长,过期自动清理
proxy: ""                           # 可选,如 socks5://127.0.0.1:1080
```

## 📁 数据与文件

```
~/.kurigram-mcp/
├── config.yaml         # setup 生成的配置(权限 600)
├── sessions/           # Telegram 会话文件:u_{API_ID}.session(每账号一个)
├── downloads/          # download_media 落盘目录
└── uploads/            # create_upload_url 暂存(按 uid 分桶,过期自动清理)
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
