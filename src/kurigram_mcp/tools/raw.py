"""深度调试工具:raw MTProto 调用与接口发现。"""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from ..telegram.raw import get_function_info, list_functions
from .common import ServerState, wrap_errors

_READ_ONLY = ToolAnnotations(read_only_hint=True)
_DESTRUCTIVE = ToolAnnotations(destructive_hint=True)


def register(mcp: MCPServer[ServerState]) -> None:
    @mcp.tool(annotations=_DESTRUCTIVE)
    @wrap_errors
    async def raw_invoke(
        ctx: Context[ServerState],
        function: str,
        params: dict | None = None,
        account: str | None = None,
    ) -> dict:
        """调用任意原始 MTProto 函数(不经过聊天白名单,谨慎使用)。
        function 如 'messages.getHistory';嵌套对象如 {"_":"inputPeerEmpty"};
        先用 get_raw_method_info 查参数;messages.* 用 inputPeer*,channels.* 用 inputChannel;64 位整数传字符串。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        return await client.raw_invoke(function, params or {})

    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def list_raw_methods(
        ctx: Context[ServerState],
        query: str | None = None,
        module: str | None = None,
        limit: int = 50,
    ) -> dict:
        """按 query/module(如 'messages'/'channels')列出可用 raw MTProto 函数清单。"""
        methods = list_functions(query=query, module=module, limit=limit)
        return {"count": len(methods), "methods": methods}

    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def get_raw_method_info(ctx: Context[ServerState], name: str) -> dict:
        """查询单个 raw MTProto 函数(如 'messages.getHistory')的参数名、类型与返回类型。"""
        return get_function_info(name)
