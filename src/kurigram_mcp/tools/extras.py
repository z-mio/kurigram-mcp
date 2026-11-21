"""扩展交互工具组(toolset=extras):视频/动图/音频/位置/联系人/骰子/清单与置顶操作。"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer

from ..telegram.extras import manage_message_extras as _manage_message_extras
from ..telegram.extras import send_extra as _send_extra
from .common import ServerState, access_for, require_chat, resolve_chat_id, wrap_errors

ExtraSendKind = Literal["video", "animation", "audio", "location", "contact", "dice", "checklist"]
ExtraMsgAction = Literal["pin", "unpin", "mark_checklist"]


def register(mcp: MCPServer[ServerState]) -> None:
    @mcp.tool()
    @wrap_errors
    async def send_extra(
        ctx: Context[ServerState],
        chat_id: int | str,
        kind: ExtraSendKind,
        params: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送扩展消息(强制白名单;括号内键放 params 字典;媒体支持路径/file_id/URL/upload://)。kind:
        video(media,caption?,parse_mode?,has_spoiler?,duration?,width?,height?,supports_streaming?) |
        animation(media,caption?,parse_mode?,has_spoiler?,duration?,width?,height?) |
        audio(media,caption?,parse_mode?,duration?,performer?,title?) |
        location(latitude,longitude,live_period?:秒,horizontal_accuracy?,heading?,proximity_alert_radius?) |
        contact(phone_number,first_name,last_name?,vcard?) |
        dice(emoji?:🎲🎯🏀⚽🎳🎰) |
        checklist(title,tasks:[str|{id?:int,text}],parse_mode?,others_can_add_tasks?,
        others_can_mark_tasks_as_done?;需 Premium,字符串任务按 1 基自动编 id)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        cid = await resolve_chat_id(client, chat_id)
        require_chat(access, cid)
        return await _send_extra(
            client,
            cid,
            kind,
            params,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def manage_message_extras(
        ctx: Context[ServerState],
        chat_id: int | str,
        action: ExtraMsgAction,
        params: dict[str, Any] | None = None,
        account: str | None = None,
    ) -> dict:
        """消息扩展操作(强制白名单;括号内键放 params 字典)。action:
        pin(message_id:int,disable_notification?:bool,both_sides?:bool) |
        unpin(message_id?:int 0为取消最新置顶) |
        mark_checklist(message_id:int,done_task_ids?:[int],not_done_task_ids?:[int],id见checklist.tasks[].id)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        cid = await resolve_chat_id(client, chat_id)
        require_chat(access, cid)
        return await _manage_message_extras(client, cid, action, params)
