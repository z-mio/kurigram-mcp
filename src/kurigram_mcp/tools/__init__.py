"""MCP 工具注册。"""

from __future__ import annotations

import time

from mcp.server.mcpserver import Context, MCPServer

from .. import __version__
from . import bot_debug, chat, raw, read
from .common import ServerState, wrap_errors


def register_tools(mcp: MCPServer) -> None:
    chat.register(mcp)
    read.register(mcp)
    bot_debug.register(mcp)
    raw.register(mcp)

    @mcp.tool()
    @wrap_errors
    async def whoami(ctx: Context, account: str | None = None) -> dict:
        """查看 Telegram 用户会话信息(用户 id、用户名、DC、会话文件位置)。
        account:账号名(缺省默认账号);不带参数时若服务器有多个账号,返回当前默认账号。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        info = await client.whoami()
        info["account"] = client.settings.account_name or "default"
        return info

    @mcp.tool()
    @wrap_errors
    async def mcp_get_server_info(ctx: Context) -> dict:
        """查看 MCP 服务器状态:版本、运行时长、已连接账号列表、默认账号、各账号白名单摘要。"""
        state: ServerState = ctx.request_context.lifespan_context
        default_client = state.client
        latency = await default_client.ping()
        accounts = []
        for name, client in state.clients.items():
            access = state.accesses.get(name)
            accounts.append(
                {
                    "name": name,
                    "connected": client.connected,
                    "whitelist": access.summary() if access else [],
                }
            )
        return {
            "version": __version__,
            "uptime_seconds": round(time.monotonic() - state.started_at, 1),
            "default_account": state.default,
            "telegram_connected": default_client.connected,
            "telegram_ping_ms": latency,
            "whitelist": state.access.summary(),
            "whitelist_count": state.access.count,
            "accounts": accounts,
        }
