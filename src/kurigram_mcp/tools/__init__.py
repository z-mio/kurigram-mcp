"""MCP 工具注册(按 toolsets 按需加载)。"""

from __future__ import annotations

import inspect
import time

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from .. import __version__
from ..config import VALID_TOOLSETS
from . import bot_debug, chat, extras, forum, raw, read, stickers
from .common import ServerState, wrap_errors

_READ_ONLY = ToolAnnotations(read_only_hint=True)


def register_tools(mcp: MCPServer, toolsets: tuple[str, ...] = VALID_TOOLSETS) -> None:
    enabled = set(toolsets)
    if "core" in enabled:
        chat.register(mcp)
        read.register(mcp)
        bot_debug.register(mcp)
    if "stickers" in enabled:
        stickers.register(mcp)
    if "forum" in enabled:
        forum.register(mcp)
    if "extras" in enabled:
        extras.register(mcp)
    if "raw" in enabled:
        raw.register(mcp)

    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def whoami(ctx: Context[ServerState], account: str | None = None) -> dict:
        """查看当前 Telegram 用户会话信息(id/username/DC/会话文件)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        info = await client.whoami()
        info["account"] = client.settings.account_name or "default"
        return info

    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def mcp_get_server_info(ctx: Context[ServerState]) -> dict:
        """查看 MCP 服务器状态:版本、运行时长、已启用工具组、已连接账号与白名单摘要。"""
        state = ctx.request_context.lifespan_context
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
            "enabled_toolsets": list(toolsets),
            "default_account": state.default,
            "telegram_connected": default_client.connected,
            "telegram_ping_ms": latency,
            "whitelist": state.access.summary(),
            "whitelist_count": state.access.count,
            "accounts": accounts,
        }

    # 统一清理多行 docstring 的缩进空白,避免冗余空格进入工具 schema
    for tool in mcp._tool_manager.list_tools():
        if tool.description:
            tool.description = inspect.cleandoc(tool.description)
