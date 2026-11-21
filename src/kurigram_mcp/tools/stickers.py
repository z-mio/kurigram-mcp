"""贴纸与贴纸包工具组(toolset=stickers):领域聚合为只读查询 + 写管理 2 个工具。"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from ..telegram.stickers import stickers_manage as _stickers_manage
from ..telegram.stickers import stickers_query as _stickers_query
from .common import ServerState, wrap_errors

StickerQueryAction = Literal[
    "get_set",
    "get_owned_sets",
    "get_custom_emoji",
    "search",
    "search_sets",
    "favorites",
    "recent",
    "suggest_name",
]

StickerManageAction = Literal[
    "install",
    "uninstall",
    "archive",
    "reorder_sets",
    "add_favorite",
    "remove_favorite",
    "add_recent",
    "remove_recent",
    "clear_recent",
    "create_set",
    "add_to_set",
    "replace_in_set",
    "delete_from_set",
    "delete_set",
    "set_title",
    "set_thumbnail",
    "set_custom_emoji_thumbnail",
    "set_emoji_list",
    "set_keywords",
    "set_mask_position",
    "set_position",
    "upload_file",
]

_READ_ONLY = ToolAnnotations(read_only_hint=True)


def register(mcp: MCPServer[ServerState]) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def stickers_query(
        ctx: Context[ServerState],
        action: StickerQueryAction,
        params: dict[str, Any] | None = None,
        account: str | None = None,
    ) -> dict:
        """查询贴纸与贴纸包(括号内键放 params 字典)。action:
        get_set(name) | get_owned_sets(limit?:int,offset_sticker_set_id?:int) |
        get_custom_emoji(custom_emoji_ids:[str]) |
        search(emojis?:[str],query?:str,sticker_type?,limit?:int,offset?:int) |
        search_sets(query,sticker_type?) | favorites | recent(is_attached?:bool) | suggest_name(title)。
        sticker_type: regular|mask|custom_emoji。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        return await _stickers_query(client, action, params)

    @mcp.tool()
    @wrap_errors
    async def stickers_manage(
        ctx: Context[ServerState],
        action: StickerManageAction,
        params: dict[str, Any] | None = None,
        account: str | None = None,
    ) -> dict:
        """管理贴纸与贴纸包(括号内键放 params 字典)。
        InputSticker={sticker(路径/file_id/URL/upload://),format(static|animated|video),
        emoji_list:[str],mask_position?:{point(forehead|eyes|mouth|chin),x_shift,y_shift,scale},keywords?:[str]}。
        sticker_type: regular|mask|custom_emoji;已有贴纸操作(sticker)传 file_id。action:
        install/uninstall/archive(name) | reorder_sets(sticker_set_ids:[int],sticker_type?) |
        add_favorite/remove_favorite(sticker) | add_recent/remove_recent(sticker,is_attached?) |
        clear_recent(is_attached?) |
        create_set(name,title,stickers:[InputSticker],sticker_type?,needs_repainting?,user_id?) |
        add_to_set(name,sticker:InputSticker,user_id?) |
        replace_in_set(old_sticker,sticker:InputSticker,user_id?) |
        delete_from_set(sticker) | delete_set(name) | set_title(name,title) |
        set_thumbnail(name,format,thumbnail?,user_id?) |
        set_custom_emoji_thumbnail(name,custom_emoji_id?) |
        set_emoji_list(sticker,emoji_list:[str]) | set_keywords(sticker,keywords?:[str]) |
        set_mask_position(sticker,mask_position?) | set_position(sticker,position:int 0基) |
        upload_file(sticker,format,user_id?)。user_id 缺省取当前账号。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        return await _stickers_manage(client, action, params)
