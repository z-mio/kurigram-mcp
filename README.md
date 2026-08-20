<div align="center">

# 🤖 kurigram-mcp

**Debug Telegram bots with AI** — a local MCP server that drives your Telegram user session over MTProto.

[![PyPI Version](https://img.shields.io/pypi/v/kurigram-mcp.svg)](https://pypi.org/project/kurigram-mcp/)
[![Python Versions](https://img.shields.io/pypi/pyversions/kurigram-mcp.svg)](https://pypi.org/project/kurigram-mcp/)
[![License](https://img.shields.io/pypi/l/kurigram-mcp.svg)](https://github.com/z-mio/kurigram-mcp/blob/main/LICENSE)

**English** · [简体中文](README.zh.md)

</div>

---

## ✨ Features

|                       |                                                                                                                       |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------|
| 🔌 **Standard MCP**   | Streamable HTTP transport, 2026-07-28 protocol, backward-compatible with 2025-11-25 clients (Claude Code, Codex, DSH) |
| 🧪 **Bot debugging**  | Send `/start`, measure reply latency, wait for events, drain update streams                                           |
| 🛠️ **Deep debugging** | `raw_invoke` any MTProto function, with built-in API discovery                                                        |
| 🔒 **Chat whitelist** | Per-client control via request header, fail-closed by default                                                         |
| ⚡ **Stateless**      | Server restarts don't break connected clients                                                                         |
| 🚀 **Zero config**    | `uv tool install`, interactive setup wizard, one-command login                                                        |

## 🚀 Quick Start

```bash
# 1. Install (provides `kurigram-mcp` and the `km` alias)
uv tool install kurigram-mcp

# 2. One-time setup: API_ID / API_HASH / whitelist / proxy / port
#    AUTH_TOKEN is auto-generated if left blank (Bearer auth on by default)
km setup

# 3. Log in (skip if you chose to during setup): phone → code → 2FA
km auth

# 4. Start the server
km run     # default: http://127.0.0.1:8765/mcp
```

> Get `API_ID` / `API_HASH` from [my.telegram.org/apps](https://my.telegram.org/apps). Login must be performed by you —
> credentials never leave your machine.

## 👥 Multi-Account Sessions

Some test scenarios need several users in the same chat (e.g. group bots). Register one
account per Telegram user — each account keeps its own session file, optional proxy and
chat whitelist:

```bash
# 1. Register an account (credentials go into ~/.kurigram-mcp/config.yaml)
km session add alice --api-id 11111111 --api-hash abc... --allowed-chat-ids "-1001234567890"
km session add bob   --api-id 22222222 --api-hash def...

# 2. Log each one in (phone → code → 2FA)
km auth alice
km auth bob

# 3. See login status offline (cached identity, no network needed)
km session list          # add -v for proxy/whitelist details

# 4. Run one server per account — different ports for simultaneous use
km run --account alice --port 8765
km run --account bob   --port 8766

# Remove an account (registry entry + .session file; -f skips confirmation)
km session remove bob
```

- The legacy single-account config (`api_id` at top level) is the implicit account **`default`**
  — existing setups keep working unchanged, and `km run` without `--account` falls back to it
  (or to the first registered account).
- Per-account `--allowed-chat-ids` overrides the global whitelist for that server; the
  per-request `X-Kurigram-Allowed-Chats` header still wins for individual calls.
- `km auth` with multiple accounts and no name shows an interactive picker.
- Tools are bound to the account the server was started with (`whoami` shows which one).

## 🧰 Tools (34)

| Group      | Tools                                                                                                                                                                                                                                                                        |
|------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 🧾 Session | `whoami`, `mcp_get_server_info`                                                                                                                                                                                                                                              |
| 📤 Send    | `send_message`, `send_photo`, `send_document`, `send_voice`, `send_sticker`, `send_media_group`, `send_poll`, `vote_poll`, `forward_message`, `edit_message`, `delete_message`, `send_chat_action`, `start_bot`, `click_inline_button`, `send_reaction`, `send_inline_query` |
| 📥 Read    | `get_chat`, `get_chat_history`, `get_messages`, `get_dialogs`, `search_messages`, `get_chat_members_count`, `download_media`                                                                                                                                                 |
| 👥 Group   | `join_chat`, `leave_chat`                                                                                                                                                                                                                                                    |
| ⏱️ Events   | `wait_for_update`(谓词含 `is_media` / `media_type`), `drain_updates`                                                                                                                                                                                                         |
| 🔬 Deep    | `raw_invoke`, `list_raw_methods`, `get_raw_method_info`                                                                                                                                                                                                                      |

## 🔌 Client Setup

```bash
# Claude Code
claude mcp add --transport http kurigram-mcp http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer <AUTH_TOKEN>" \
  --header "X-Kurigram-Allowed-Chats: 6540476263"   # optional per-client whitelist
```

```toml
# Codex (~/.codex/config.toml)
[mcp_servers.kurigram-mcp]
url = "http://127.0.0.1:8765/mcp"
http_headers = { "Authorization" = "Bearer <AUTH_TOKEN>", "X-Kurigram-Allowed-Chats" = "6540476263" }
```

```yaml
# DSH — cordis.yml plugin row (@deepseek-ai/dsh-mcp-client)
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

### 🔐 Chat Whitelist

1. **Request header `X-Kurigram-Allowed-Chats`** — per-client declaration (comma-separated: numeric chat ids,
   `@username`,
   `me`).
2. **Config `allowed_chat_ids`** — fallback when the header is absent.

Fail-closed: chats outside the whitelist are rejected with `[NOT_WHITELISTED]`; `get_dialogs` only returns whitelisted
chats.

## ⚙️ Configuration

All configuration lives in **one file**: `~/.kurigram-mcp/config.yaml`.

```yaml
api_id: 123456
api_hash: your_hash
allowed_chat_ids: "123456789,me"   # fallback whitelist
host: 127.0.0.1
port: 8765
auth_token: auto_generated_or_yours # Bearer auth
proxy: ""                           # optional, e.g. socks5://127.0.0.1:1080
```

## 📁 Data & Files

```
~/.kurigram-mcp/
├── config.yaml         # setup-generated config (chmod 600)
├── u_{API_ID}.session  # Telegram session (bound to API_ID, persists)
└── downloads/          # download_media output
```

## 🧑‍💻 Development

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts

# Configure like a regular user (shared ~/.kurigram-mcp):
uv run kurigram-mcp setup
# Or isolate a dev environment (never touches your real config):
# KURIGRAM_MCP_HOME=$PWD/.dev-home uv run kurigram-mcp setup
# KURIGRAM_MCP_HOME=$PWD/.dev-home uv run kurigram-mcp run
```

## 📄 License

[MIT](LICENSE)
