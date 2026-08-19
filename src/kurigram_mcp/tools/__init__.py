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
    async def whoami(ctx: Context) -> dict:
        """查看当前 Telegram 用户会话信息(用户 id、用户名、DC、会话文件位置)。"""
        state: ServerState = ctx.request_context.lifespan_context
        return await state.client.whoami()

    @mcp.tool()
    @wrap_errors
    async def mcp_get_server_info(ctx: Context) -> dict:
        """查看 MCP 服务器状态:版本、运行时长、Telegram 连接与延迟、白名单摘要。"""
        state: ServerState = ctx.request_context.lifespan_context
        latency = await state.client.ping()
        return {
            "version": __version__,
            "uptime_seconds": round(time.monotonic() - state.started_at, 1),
            "telegram_connected": state.client.connected,
            "telegram_ping_ms": latency,
            "whitelist": state.access.summary(),
            "whitelist_count": state.access.count,
        }
