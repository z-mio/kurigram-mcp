"""聊天操作工具:发送/编辑/删除/动作/媒体/轮询/群成员。全部强制白名单校验。

chat_id 参数统一支持:数字 id(含群/频道负 ID)、@username、me(Saved Messages)。
所有工具支持 account 参数:指定操作账号(缺省用服务器默认账号)。
"""

from __future__ import annotations

import secrets
from typing import Literal
from urllib.parse import quote

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from ..errors import INTERNAL, McpError
from ..files import sanitize_name
from .common import (
    ServerState,
    access_for,
    require_chat,
    resolve_chat_id,
    wrap_errors,
)

ParseModeArg = Literal["none", "markdown", "html"]
RichFormatArg = Literal["markdown", "html"]
ChatActionArg = Literal[
    "typing",
    "upload_photo",
    "record_video",
    "upload_video",
    "record_audio",
    "upload_audio",
    "upload_document",
    "find_location",
    "record_video_note",
    "upload_video_note",
    "playing",
    "choose_contact",
    "speaking",
    "import_history",
    "choose_sticker",
    "cancel",
]
_DESTRUCTIVE = ToolAnnotations(destructive_hint=True)


def register(mcp: MCPServer[ServerState]) -> None:
    @mcp.tool()
    @wrap_errors
    async def create_upload_url(ctx: Context[ServerState], file_name: str) -> dict:
        """生成一次性上传 URL(`curl -T <文件> '<url>'`),
        返回 upload://<uid>/<name> 供各类发送工具的 media/sticker 参数使用。"""
        state = ctx.request_context.lifespan_context
        gateway = state.files
        if gateway is None:
            raise McpError(INTERNAL, "文件网关未启用(lifespan 未完成)")
        name = sanitize_name(file_name)
        uid = secrets.token_urlsafe(16)
        token = gateway.sign({"scope": "upload", "uid": uid, "name": name, "max": gateway.max_upload_bytes})
        url = f"{gateway.base_url}/upload/{quote(name)}?token={token}"
        return {
            "url": url,
            "media": f"upload://{uid}/{name}",
            "max_bytes": gateway.max_upload_bytes,
            "expires_in": gateway.ttl,
            "usage": f"curl -T <本地文件> '{url}'",
        }

    @mcp.tool()
    @wrap_errors
    async def send_message(
        ctx: Context[ServerState],
        chat_id: int | str,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: ParseModeArg = "none",
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送文本消息。message_thread_id:论坛话题 ID。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_message(
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
            parse_mode=parse_mode,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_rich_message(
        ctx: Context[ServerState],
        chat_id: int | str,
        content: str,
        format: RichFormatArg = "markdown",
        media: list[dict] | None = None,
        reply_to_message_id: int | None = None,
        is_rtl: bool = False,
        skip_entity_detection: bool = False,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送富消息(标题/列表/表格/折叠块/公式/按钮行)。
        media: [{id:str, media(路径/file_id/URL/upload://),
        type?(photo|video|audio|document|animation|voice,缺省按扩展名推断)}] 供 tg://<type>?id=<id> 引用。
        若返回 rich 为 null 用 get_messages 回读;非 Premium 账号会报 RICH_MESSAGE_UNSUPPORTED。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_rich_message(
            chat_id,
            content,
            format=format,
            media=media,
            reply_to_message_id=reply_to_message_id,
            is_rtl=is_rtl,
            skip_entity_detection=skip_entity_detection,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_photo(
        ctx: Context[ServerState],
        chat_id: int | str,
        media: str,
        caption: str | None = None,
        parse_mode: ParseModeArg = "none",
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送图片。media:本地路径|file_id|URL|upload://。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_photo(
            chat_id,
            media,
            caption=caption,
            parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_document(
        ctx: Context[ServerState],
        chat_id: int | str,
        media: str,
        caption: str | None = None,
        parse_mode: ParseModeArg = "none",
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送文件。media:本地路径|file_id|URL|upload://。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_document(
            chat_id,
            media,
            caption=caption,
            parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_voice(
        ctx: Context[ServerState],
        chat_id: int | str,
        media: str,
        caption: str | None = None,
        parse_mode: ParseModeArg = "none",
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送语音。media:本地路径|file_id|URL|upload://(建议 .ogg/.mp3)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_voice(
            chat_id,
            media,
            caption=caption,
            parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_sticker(
        ctx: Context[ServerState],
        chat_id: int | str,
        media: str,
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送贴纸。media:本地 .webp/.tgs/.webm 路径|file_id|URL|upload://。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_sticker(
            chat_id,
            media,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_media_group(
        ctx: Context[ServerState],
        chat_id: int | str,
        media: list,
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送相册(媒体组)。media 条目:字符串或 {media, type?(photo/document/video/audio), caption?, parse_mode?}。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_media_group(
            chat_id,
            media,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_poll(
        ctx: Context[ServerState],
        chat_id: int | str,
        question: str,
        options: list[str],
        is_anonymous: bool = True,
        allows_multiple_answers: bool = False,
        allows_revoting: bool = False,
        is_quiz: bool = False,
        correct_option_id: int | None = None,
        explanation: str | None = None,
        open_period: int | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """发送投票/测验。is_quiz=true 时需设 correct_option_id(0基)且与多选互斥;open_period 单位秒。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_poll(
            chat_id,
            question,
            options,
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers,
            allows_revoting=allows_revoting,
            is_quiz=is_quiz,
            correct_option_id=correct_option_id,
            explanation=explanation,
            open_period=open_period,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def vote_poll(
        ctx: Context[ServerState],
        chat_id: int | str,
        message_id: int,
        options: int | list[int],
        account: str | None = None,
    ) -> dict:
        """给投票/测验投票(触发 bot 的 poll_answer 更新)。options:0 基选项下标或下标列表。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.vote_poll(chat_id, message_id, options)

    @mcp.tool()
    @wrap_errors
    async def forward_message(
        ctx: Context[ServerState],
        chat_id: int | str,
        from_chat_id: int | str,
        message_ids: int | list[int],
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """转发消息(message_ids 单条或列表;from_chat_id 与 chat_id 均需在白名单)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        from_chat_id = await resolve_chat_id(client, from_chat_id)
        require_chat(access, chat_id)
        require_chat(access, from_chat_id)
        return await client.forward_message(chat_id, from_chat_id, message_ids, message_thread_id=message_thread_id)

    @mcp.tool()
    @wrap_errors
    async def join_chat(ctx: Context[ServerState], chat_id: int | str, account: str | None = None) -> dict:
        """加入群/频道(支持数字 id/@username/邀请链接 t.me/+xxx)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        s = str(chat_id).strip()
        if s.lstrip("-").isdigit():
            chat_id = int(s)
            require_chat(access, chat_id)
        elif not _is_invite_link(s):
            chat_id = await resolve_chat_id(client, chat_id)
            require_chat(access, chat_id)
        return await client.join_chat(chat_id)

    @mcp.tool(annotations=_DESTRUCTIVE)
    @wrap_errors
    async def leave_chat(ctx: Context[ServerState], chat_id: int | str, account: str | None = None) -> dict:
        """退出群/频道(触发 bot 的 left_chat_member 更新)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.leave_chat(chat_id)

    @mcp.tool()
    @wrap_errors
    async def edit_message(
        ctx: Context[ServerState],
        chat_id: int | str,
        message_id: int,
        text: str,
        account: str | None = None,
    ) -> dict:
        """编辑自己发送的消息。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.edit_message(chat_id, message_id, text)

    @mcp.tool(annotations=_DESTRUCTIVE)
    @wrap_errors
    async def delete_message(
        ctx: Context[ServerState], chat_id: int | str, message_id: int, account: str | None = None
    ) -> dict:
        """删除消息(双方可见,revoke)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.delete_message(chat_id, message_id)

    @mcp.tool()
    @wrap_errors
    async def send_chat_action(
        ctx: Context[ServerState],
        chat_id: int | str,
        action: ChatActionArg = "typing",
        account: str | None = None,
    ) -> dict:
        """发送聊天状态动作(MTProto 层对 bot 可见)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_chat_action(chat_id, action)

    @mcp.tool()
    @wrap_errors
    async def click_inline_button(
        ctx: Context[ServerState],
        chat_id: int | str,
        message_id: int,
        button_text: str | None = None,
        row_index: int = 0,
        col_index: int = 0,
        data: str | None = None,
        account: str | None = None,
    ) -> dict:
        """点击消息上的 inline 或富消息按钮(触发 callback_query)。
        定位优先级:data(callback_data)> button_text > row_index/col_index;url/copy_text 按钮直接返回值。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.click_inline_button(
            chat_id,
            message_id,
            button_text=button_text,
            row_index=row_index,
            col_index=col_index,
            data=data,
        )

    @mcp.tool()
    @wrap_errors
    async def send_reaction(
        ctx: Context[ServerState],
        chat_id: int | str,
        message_id: int,
        emoji: str,
        big: bool = False,
        account: str | None = None,
    ) -> dict:
        """给消息发送 reaction(测试 bot 的 reaction 处理)。emoji 如 👍 ❤️ 🔥。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        return await client.send_reaction(chat_id, message_id, emoji, big=big)


def _is_invite_link(s: str) -> bool:
    """t.me/+xxx / t.me/joinchat/xxx 邀请链接。"""
    import re

    return re.match(r"(?:https?://)?(?:t|telegram)\.me/(?:\+|joinchat/)", s) is not None
