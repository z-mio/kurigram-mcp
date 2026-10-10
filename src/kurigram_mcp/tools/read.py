"""读取工具:聊天信息/历史/消息/对话框/搜索/成员数。全部强制白名单校验。

所有工具支持 account 参数:指定操作账号(缺省用服务器默认账号)。
"""

from __future__ import annotations

import shlex

from mcp.server.mcpserver import Context, MCPServer

from ..errors import INTERNAL, McpError
from ..files import media_info
from .common import ServerState, access_for, require_chat, resolve_chat_id, wrap_errors


def register(mcp: MCPServer[ServerState]) -> None:
    @mcp.tool()
    @wrap_errors
    async def get_chat(ctx: Context[ServerState], chat_id: int | str, account: str | None = None) -> dict:
        """获取聊天完整资料(标题、用户名、类型、描述、成员数等)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.get_chat(chat_id)

    @mcp.tool()
    @wrap_errors
    async def get_chat_history(
        ctx: Context[ServerState],
        chat_id: int | str,
        limit: int = 50,
        offset_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """读取聊天历史,新的在前(新→旧)。翻页:把返回的 next_offset_id 作为下次的 offset_id。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.get_chat_history(chat_id, limit=limit, offset_id=offset_id)

    @mcp.tool()
    @wrap_errors
    async def get_messages(
        ctx: Context[ServerState],
        chat_id: int | str,
        message_ids: list[int],
        account: str | None = None,
    ) -> dict:
        """按 id 获取指定消息。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.get_messages(chat_id, message_ids)

    @mcp.tool()
    @wrap_errors
    async def get_dialogs(ctx: Context[ServerState], account: str | None = None) -> dict:
        """列出所有会话,仅返回白名单内的聊天。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        return await client.get_dialogs(access.ids())

    @mcp.tool()
    @wrap_errors
    async def search_messages(
        ctx: Context[ServerState],
        chat_id: int | str,
        query: str,
        limit: int = 20,
        account: str | None = None,
    ) -> dict:
        """在聊天内搜索消息(按相关性,新→旧)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.search_messages(chat_id, query, limit=limit)

    @mcp.tool()
    @wrap_errors
    async def get_chat_members_count(ctx: Context[ServerState], chat_id: int | str, account: str | None = None) -> dict:
        """群/频道成员数(join/leave 测试后断言成员数变化)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.get_chat_members_count(chat_id)

    @mcp.tool()
    @wrap_errors
    async def download_media(
        ctx: Context[ServerState],
        chat_id: int | str,
        message_id: int,
        path: str | None = None,
        account: str | None = None,
    ) -> dict:
        """下载消息中的媒体到本地路径(默认 downloads/<chat_id>/<message_id>),返回绝对路径供进一步读取。
        远程客户端拿不到服务器本地文件:远程使用请用 get_media_url 生成签名下载 URL。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.download_media(chat_id, message_id, path)

    @mcp.tool()
    @wrap_errors
    async def get_media_url(
        ctx: Context[ServerState],
        chat_id: int | str,
        message_id: int,
        account: str | None = None,
    ) -> dict:
        """生成消息媒体的短时效签名下载 URL(远程客户端经 HTTP 直接拉取,支持 Range 断点续传)。

        返回的 url 可直接 `curl -o <file_name> '<url>'` 下载;过期后重新调用本工具即可。
        URL 绑定账号/聊天/消息,泄露窗口仅限 expires_in 秒。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        gateway = state.files
        if gateway is None:
            raise McpError(INTERNAL, "文件网关未启用(lifespan 未完成)")
        msg = await client.raw.get_messages(chat_id, message_id)
        info = media_info(msg, message_id)
        if info is None:
            raise McpError("NO_MEDIA", f"消息 {message_id} 没有可下载媒体(或已被删除)")
        acc = client.settings.account_name or state.default
        token = gateway.sign({"scope": "download", "acc": acc, "chat": chat_id, "msg": message_id})
        url = f"{gateway.base_url}/files/{chat_id}/{message_id}?token={token}"
        return {
            "url": url,
            "file_name": info["file_name"],
            "mime_type": info["mime_type"],
            "size_bytes": info["size"],
            "expires_in": gateway.ttl,
            "usage": f"curl -o {shlex.quote(info['file_name'])} '{url}'",
        }
