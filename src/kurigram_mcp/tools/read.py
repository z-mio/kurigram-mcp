"""读取工具:聊天信息/历史/消息/对话框/搜索/成员数。全部强制白名单校验。

所有工具支持 account 参数:指定操作账号(缺省用服务器默认账号)。
"""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer

from .common import ServerState, access_for, require_chat, resolve_chat_id, wrap_errors


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @wrap_errors
    async def get_chat(
        ctx: Context, chat_id: int | str, account: str | None = None
    ) -> dict:
        """获取聊天完整资料(标题、用户名、类型、描述、成员数等)。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = await access_for(ctx, state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.get_chat(chat_id)

    @mcp.tool()
    @wrap_errors
    async def get_chat_history(
        ctx: Context,
        chat_id: int | str,
        limit: int = 50,
        offset_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """读取聊天历史,新的在前(新→旧)。翻页:把返回的 next_offset_id 作为下次的 offset_id。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = await access_for(ctx, state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.get_chat_history(chat_id, limit=limit, offset_id=offset_id)

    @mcp.tool()
    @wrap_errors
    async def get_messages(
        ctx: Context,
        chat_id: int | str,
        message_ids: list[int],
        account: str | None = None,
    ) -> dict:
        """按 id 获取指定消息。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = await access_for(ctx, state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.get_messages(chat_id, message_ids)

    @mcp.tool()
    @wrap_errors
    async def get_dialogs(ctx: Context, account: str | None = None) -> dict:
        """列出所有会话,仅返回白名单内的(不泄露其他聊天)。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = await access_for(ctx, state, account)
        return await client.get_dialogs(access.ids())

    @mcp.tool()
    @wrap_errors
    async def search_messages(
        ctx: Context,
        chat_id: int | str,
        query: str,
        limit: int = 20,
        account: str | None = None,
    ) -> dict:
        """在聊天内搜索消息(按相关性,新→旧)。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = await access_for(ctx, state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.search_messages(chat_id, query, limit=limit)

    @mcp.tool()
    @wrap_errors
    async def get_chat_members_count(
        ctx: Context, chat_id: int | str, account: str | None = None
    ) -> dict:
        """群/频道成员数(join/leave 测试后断言成员数变化)。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = await access_for(ctx, state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.get_chat_members_count(chat_id)

    @mcp.tool()
    @wrap_errors
    async def download_media(
        ctx: Context,
        chat_id: int | str,
        message_id: int,
        path: str | None = None,
        account: str | None = None,
    ) -> dict:
        """下载消息中的媒体到本地路径(默认 downloads/<chat_id>/<message_id>),返回绝对路径供进一步读取。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = await access_for(ctx, state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.download_media(chat_id, message_id, path)
