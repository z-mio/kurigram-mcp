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
| 🔒 **Chat whitelist** | Per-account whitelist with global fallback, fail-closed by default                                                    |
| ⚡ **Stateless**      | Clients stay connected across server restarts                                                                         |
| 🚀 **Zero config**    | `uv tool install`, interactive setup wizard, one-command login                                                        |

## 🚀 Quick Start

```bash
# 1. Install (provides `kurigram-mcp` and the `km` alias)
uv tool install kurigram-mcp

# 2. One-time setup: API_ID / API_HASH / whitelist / proxy
#    AUTH_TOKEN is auto-generated (Bearer auth on by default)
km setup

# 3. Log in
km session add          # interactive wizard: name → credentials → whitelist → phone → code → 2FA

# 4. Start the server (foreground — stop with Ctrl-C)
km run     # default: http://127.0.0.1:8765/mcp
```

> Get `API_ID` / `API_HASH` from [my.telegram.org/apps](https://my.telegram.org/apps). Login must be performed by you —
> credentials stay on your machine.

## 👥 Multi-Account Sessions

Some test scenarios need several users in the same chat (e.g. group bots). Register one account per Telegram user — each
account keeps its own session file, optional proxy and chat whitelist — then **all accounts live in one server**, and
every tool takes an
`account` parameter:

```bash
# 1. Add each account
km session add alice    # interactive wizard; credentials can reuse the setup app by default
km session add bob

# 2. See login status
km session list          # add -v for proxy/whitelist details

# 3. Edit an account's whitelist / proxy
km session set alice --allowed-chat-ids="-1001234567890,@mybot,me"   # note: use `=` for values starting with `-`
km session set alice --allowed-chat-ids ""   # clear → fall back to global whitelist
km session set bob --proxy socks5://127.0.0.1:1080   # or --proxy "" to clear

# 4. Start ONE server — all logged-in accounts connect together
km run                   # every tool now accepts account="alice" / account="bob"
```

- Every tool (send, read, events, raw, `whoami`) accepts `account: <name>` — omit it to use the default account.
  Example: `send_message(account="alice")` → `wait_for_update(account="alice")`.
- `km run --account alice` starts a single-account server (isolation mode).
- The legacy single-account config (`api_id` at top level) is the implicit account **`default`**.
- Per-account `--allowed-chat-ids` overrides the global whitelist for that account; accounts without their own whitelist
  fall back to the global `allowed_chat_ids`.
- `mcp_get_server_info` lists all connected accounts.
- Short flags: `km run -a/--account -H/--host -p/--port -u/--public-url -s/--stateful`;
  `km session add/set -x/--proxy -c/--allowed-chat-ids`; `km -V/--version`.

## 🧰 Tools (36)

| Group      | Tools                                                                                                                                                                                                                                                                        |
|------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 🧾 Session | `whoami`, `mcp_get_server_info`                                                                                                                                                                                                                                              |
| 📤 Send    | `send_message`, `send_rich_message`, `send_photo`, `send_document`, `send_voice`, `send_sticker`, `send_media_group`, `send_poll`, `vote_poll`, `forward_message`, `edit_message`, `delete_message`, `send_chat_action`, `start_bot`, `click_inline_button`, `send_reaction`, `send_inline_query`, `create_upload_url` |
| 📥 Read    | `get_chat`, `get_chat_history`, `get_messages`, `get_dialogs`, `search_messages`, `get_chat_members_count`, `download_media`, `get_media_url`                                                                                                                               |
| 👥 Group   | `join_chat`, `leave_chat`                                                                                                                                                                                                                                                    |
| ⏱️ Events   | `wait_for_update` (predicates include `is_media` / `media_type`), `drain_updates`                                                                                                                                                                                          |
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

### 📁 Remote File Transfer

Remote MCP clients can't reach the server's local filesystem, so media transfer goes through
short-lived signed URLs (presigned-URL pattern):

- **Download** — `get_media_url(chat_id, message_id)` returns `{url, file_name, mime_type,
  size_bytes}`; `curl -o <file_name> '<url>'` fetches the media over plain HTTP
  (`GET /files/<chat>/<msg>`, `Range` supported for resume).
- **Upload** — `create_upload_url(file_name)` returns `{url, media}`;
  `curl -T <local file> '<url>'` PUTs the file into a per-upload staging dir, then pass `media`
  (`upload://<uid>/<name>`) directly to `send_photo` / `send_document` / `send_voice` /
  `send_sticker` / `send_media_group` / `send_rich_message`.

Tokens are HS256 JWTs signed by an in-process key (a restart invalidates all outstanding URLs),
each bound to a single resource, expiring after `file_url_ttl_seconds` (default 900s). Upload URLs
are single-use; staged files are cleaned up after `upload_retention_hours` (default 24h).

For humans and scripts, the master `AUTH_TOKEN` is also accepted — via the
`Authorization: Bearer` header only (never as `?token=`):

```bash
curl -T a.png -H "Authorization: Bearer $AUTH_TOKEN" http://host:port/upload/a.png
curl -H "Authorization: Bearer $AUTH_TOKEN" -o x http://host:port/files/<chat_id>/<message_id>
```

> **Public URL (reverse proxy / Cloudflare Tunnel)**: when the server is reached from outside,
> pass `-u, --public-url` so generated upload/download links point at the external address — the
> proxy rewrites the `Host` header, which is why the server never derives URLs from requests.
> Not needed for local-only use:
>
> ```bash
> km run --public-url https://kurigram.example.com
> ```
>
> (`PUBLIC_BASE_URL` env or `public_base_url` in config.yaml work too; the flag wins.) Note that
> Cloudflare's proxy caps request bodies at 100 MB on Free/Pro plans: larger uploads through the
> tunnel get a 413 from Cloudflare itself (downloads are unaffected).

## ⚙️ Configuration

All configuration lives in **one file**: `~/.kurigram-mcp/config.yaml`.

```yaml
api_id: 123456
api_hash: your_hash
allowed_chat_ids: "123456789,me"   # global fallback whitelist (per-account overrides it)
host: 127.0.0.1
port: 8765
auth_token: auto_generated_or_yours # Bearer auth
public_base_url: ""                 # public URL when reached from outside (e.g. tunnel domain); skip for local-only use
file_url_ttl_seconds: 900           # signed file URL lifetime
upload_max_bytes: 2147483648        # per-upload size cap (2 GiB)
upload_retention_hours: 24          # staged upload retention before cleanup
proxy: ""                           # optional, e.g. socks5://127.0.0.1:1080
```

## 📁 Data & Files

```
~/.kurigram-mcp/
├── config.yaml         # setup-generated config (chmod 600)
├── sessions/           # Telegram session files: u_{API_ID}.session (one per account)
├── downloads/          # download_media output
├── uploads/            # create_upload_url staging (per-uid dirs, auto-cleaned after retention)
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
