"""深度调试工具:raw MTProto 调用与接口发现。"""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer

from ..telegram.raw import get_function_info, list_functions
from .common import ServerState, wrap_errors


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @wrap_errors
    async def raw_invoke(ctx: Context, function: str, params: dict | None = None) -> dict:
        """直接调用 Telegram MTProto 原始函数(深度调试兜底)。

        函数名:Telegram API 的 snake 路径,如 messages.getHistory / help.getConfig /
        account.getAccountTTL / messages.getDialogs。
        参数:JSON 对象;嵌套对象用 {"_": "类型名", 字段...} 形式
        (如 {"_": "inputPeerEmpty"})。
        方法/类型清单见 https://core.telegram.org/methods 与 kurigram 的 pyrogram.raw 包。

        peer 类型选择(高频踩坑):messages.* 系函数(如 messages.getHistory /
        messages.sendInlineBotResult)的 peer 参数用 inputPeerChannel / inputPeerUser /
        inputPeerSelf;channels.* 系函数(如 channels.getChannels)才用 inputChannel。
        用错类型会报 PEER_ID_INVALID 且难排查。64 位整数(access_hash/query_id)经
        JS 客户端传输会丢精度,失败时改用字符串传参。

        注意:raw 调用不做白名单或安全过滤,可执行任意操作(包括删除、修改账号设置),请谨慎使用。
        """
        state: ServerState = ctx.request_context.lifespan_context
        return await state.client.raw_invoke(function, params or {})

    @mcp.tool()
    @wrap_errors
    async def list_raw_methods(
        ctx: Context,
        query: str | None = None,
        module: str | None = None,
        limit: int = 50,
    ) -> dict:
        """列出可用的 raw MTProto 函数(按 query 过滤名称、按 module 过滤模块)。

        返回 name + 参数名 + 返回类型,用于发现"有哪些底层能力"。
        示例:query="getChat" 找聊天相关;module="messages" 只看消息模块。
        """
        state: ServerState = ctx.request_context.lifespan_context  # noqa: F841 - 保持签名一致
        methods = list_functions(query=query, module=module, limit=limit)
        return {"count": len(methods), "methods": methods}

    @mcp.tool()
    @wrap_errors
    async def get_raw_method_info(ctx: Context, name: str) -> dict:
        """查询单个 raw MTProto 函数的完整定义:参数名、参数类型、返回类型。

        在调用 raw_invoke 前先查这里,避免参数名/类型错误。
        示例:get_raw_method_info("messages.getDialogs")
        """
        state: ServerState = ctx.request_context.lifespan_context  # noqa: F841 - 保持签名一致
        return get_function_info(name)
