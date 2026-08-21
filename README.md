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
| 🔒 **Chat whitelist** | Per-account whitelist with global fallback, fail-closed by default                                                         |
| ⚡ **Stateless**      | Server restarts don't break connected clients                                                                         |
| 🚀 **Zero config**    | `uv tool install`, interactive setup wizard, one-command login                                                        |

## 🚀 Quick Start

```bash
# 1. Install (provides `kurigram-mcp` and the `km` alias)
uv tool install kurigram-mcp

# 2. One-time setup: API_ID / API_HASH / whitelist / proxy
#    AUTH_TOKEN is auto-generated (Bearer auth on by default); setup ends with login
km setup

# 3. Log in at any time — adding an account *is* logging in
km session add          # interactive wizard: name → credentials → whitelist → phone → code → 2FA

# 4. Start the server
km run     # default: http://127.0.0.1:8765/mcp

# 5. Overview & apply changes
km status               # server state + account table in one glance
km restart              # restart the running server (picks up account/whitelist changes)
```

> Get `API_ID` / `API_HASH` from [my.telegram.org/apps](https://my.telegram.org/apps). Login must be performed by you —
> credentials never leave your machine. `km session add` **fails (and records nothing) if login fails**;
> re-running it on an existing account re-verifies (server online ⇒ session OK) or re-logs-in.

## 👥 Multi-Account Sessions

Some test scenarios need several users in the same chat (e.g. group bots). Register one
account per Telegram user — each account keeps its own session file, optional proxy and
chat whitelist — then **all accounts live in one server**, and every tool takes an
`account` parameter:

```bash
# 1. Add each account — registering *is* logging in (login failure ⇒ nothing recorded)
km session add alice    # interactive wizard; credentials can reuse the setup app by default
km session add bob

# 2. See login status offline (cached identity, no network needed)
km session list          # add -v for proxy/whitelist details

# 3. Edit an account's whitelist/proxy later (restart the server to apply)
km session set alice --allowed-chat-ids="-1001234567890,@mybot,me"   # note: use `=` for values starting with `-`
km session set alice --allowed-chat-ids ""   # clear → fall back to global whitelist
km session set bob --proxy socks5://127.0.0.1:1080   # or --proxy "" to clear

# 4. Start ONE server — all logged-in accounts connect together
km run                   # every tool now accepts account="alice" / account="bob"
```

- Every tool (send, read, events, raw, `whoami`) accepts `account: <name>` — omit it to use
  the default account. Example: `send_message(account="alice")` → `wait_for_update(account="alice")`.
- Event buses are per-account: `wait_for_update` / `expect_silent` / `drain_updates` only see
  that account's events — ideal for orchestrating alice/bob/bot interactions in one flow.
- `km run --account alice` starts a single-account server (isolation mode); un-logged-in
  accounts are skipped with a warning.
- The legacy single-account config (`api_id` at top level) is the implicit account **`default`**
  — existing setups keep working unchanged.
- Per-account `--allowed-chat-ids` overrides the global whitelist for that account; accounts
  without their own whitelist fall back to the global `allowed_chat_ids`.
- Re-running `km session add <name>` on an existing account: server online ⇒ session is fine;
  otherwise it verifies the session file and re-logs-in if invalid (credentials/whitelist are kept
  on failure — nothing is deleted).
- `mcp_get_server_info` lists all connected accounts.

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
  --header "Authorization: Bearer <AUTH_TOKEN>"
```

```toml
# Codex (~/.codex/config.toml)
[mcp_servers.kurigram-mcp]
url = "http://127.0.0.1:8765/mcp"
http_headers = { "Authorization" = "Bearer <AUTH_TOKEN>" }
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
```

### 🔐 Chat Whitelist

1. **Per-account whitelist** — `km session add NAME --allowed-chat-ids "..."` (comma-separated:
   numeric chat ids, `@username`, `me`). Each account is isolated.
2. **Global fallback** — config `allowed_chat_ids` applies to any account that didn't set its own.

Fail-closed: chats outside the whitelist are rejected with `[NOT_WHITELISTED]`; `get_dialogs` only returns whitelisted
chats; events from non-whitelisted chats are dropped before reaching the event bus.

## ⚙️ Configuration

All configuration lives in **one file**: `~/.kurigram-mcp/config.yaml`.

```yaml
api_id: 123456
api_hash: your_hash
allowed_chat_ids: "123456789,me"   # global fallback whitelist (per-account overrides it)
host: 127.0.0.1
port: 8765
auth_token: auto_generated_or_yours # Bearer auth
proxy: ""                           # optional, e.g. socks5://127.0.0.1:1080
```

## 📁 Data & Files

```
~/.kurigram-mcp/
├── config.yaml         # setup-generated config (chmod 600)
├── sessions/           # Telegram session files: u_{API_ID}.session (one per account)
├── downloads/          # download_media output
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
