"""论坛话题工具组(toolset=forum):聚合全部 13 个话题查询与管理操作。"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer

from ..telegram.forum import manage_forum_topics as _manage_forum_topics
from .common import ServerState, access_for, require_chat, resolve_chat_id, wrap_errors

ForumAction = Literal[
    "list",
    "get_by_id",
    "create",
    "edit",
    "close",
    "reopen",
    "delete",
    "pin",
    "unpin",
    "hide_general",
    "unhide_general",
    "unpin_all_messages",
    "toggle",
]


def register(mcp: MCPServer[ServerState]) -> None:
    @mcp.tool()
    @wrap_errors
    async def manage_forum_topics(
        ctx: Context[ServerState],
        chat_id: int | str,
        action: ForumAction,
        params: dict[str, Any] | None = None,
        account: str | None = None,
    ) -> dict:
        """论坛群话题查询与管理(强制白名单;括号内键放 params 字典)。action:
        list(limit?:int) | get_by_id(topic_ids:[int]) |
        create(name,icon_color?:int 可省略取默认色,icon_custom_emoji_id?:str) |
        edit(message_thread_id:int,name?,icon_custom_emoji_id?) |
        close/reopen/delete/pin/unpin(message_thread_id:int) |
        hide_general | unhide_general | unpin_all_messages(message_thread_id:int) |
        toggle(is_forum?:bool,has_forum_tabs?:bool,has_forum_sidebar?:bool)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        cid = await resolve_chat_id(client, chat_id)
        require_chat(access, cid)
        return await _manage_forum_topics(client, cid, action, params)
