"""聊天操作工具:发送/编辑/删除/动作/媒体/轮询/群成员。全部强制白名单校验。

chat_id 参数统一支持:数字 id(含群/频道负 ID)、@username、me(Saved Messages)。
"""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer

from .common import (
    ServerState,
    access_for,
    require_chat,
    resolve_chat_id,
    wrap_errors,
)


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @wrap_errors
    async def send_message(
        ctx: Context,
        chat_id: int | str,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str = "none",
    ) -> dict:
        """发送文本消息。parse_mode: none | markdown | html(如 <b>粗体</b>、<tg-spoiler>剧透</tg-spoiler>、<i>斜体</i>)。仅文本;发送投票请用 send_poll(返回里的 poll 字段仅投票消息才有)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_message(
            chat_id, text, reply_to_message_id=reply_to_message_id, parse_mode=parse_mode
        )

    @mcp.tool()
    @wrap_errors
    async def send_photo(
        ctx: Context,
        chat_id: int | str,
        media: str,
        caption: str | None = None,
        parse_mode: str = "none",
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送图片。media:本地路径(服务器侧可访问)| Telegram file_id | http(s) URL;媒体类型按扩展名自动识别(图片→photo)。caption 会出现在返回的 text 字段。parse_mode: none | markdown | html(作用于 caption)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_photo(
            chat_id, media, caption=caption, parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_document(
        ctx: Context,
        chat_id: int | str,
        media: str,
        caption: str | None = None,
        parse_mode: str = "none",
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送文件。media:本地路径(服务器侧可访问)| Telegram file_id | http(s) URL;媒体类型按扩展名自动识别(如 .ogg→voice、.webp→sticker)。caption 会出现在返回的 text 字段。parse_mode: none | markdown | html(作用于 caption)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_document(
            chat_id, media, caption=caption, parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_voice(
        ctx: Context,
        chat_id: int | str,
        media: str,
        caption: str | None = None,
        parse_mode: str = "none",
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送语音(voice note)。media:本地路径(服务器侧可访问)| Telegram file_id | http(s) URL;建议用 .ogg/.mp3 音频文件。caption 会出现在返回的 text 字段。parse_mode: none | markdown | html(作用于 caption)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_voice(
            chat_id, media, caption=caption, parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
        )

    @mcp.tool()
    @wrap_errors
    async def send_sticker(
        ctx: Context,
        chat_id: int | str,
        media: str,
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送贴纸。media:本地 .webp 路径 | Telegram file_id | http(s) URL。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_sticker(chat_id, media, reply_to_message_id=reply_to_message_id)

    @mcp.tool()
    @wrap_errors
    async def send_media_group(
        ctx: Context,
        chat_id: int | str,
        media: list,
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送相册(媒体组)。media 条目:字符串(路径/file_id/URL)或
        {"media": ..., "type": "photo"|"document", "caption": ...}。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_media_group(
            chat_id, media, reply_to_message_id=reply_to_message_id
        )

    @mcp.tool()
    @wrap_errors
    async def send_poll(
        ctx: Context,
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
    ) -> dict:
        """发送投票/测验(测试 bot 的 poll 处理)。options 为选项文本列表;
        is_quiz 时可用 correct_option_id(0 基)+ explanation。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_poll(
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
        )

    @mcp.tool()
    @wrap_errors
    async def vote_poll(
        ctx: Context,
        chat_id: int | str,
        message_id: int,
        options: int | list[int],
    ) -> dict:
        """给投票/测验投票(触发 bot 的 poll_answer 更新)。options:选项下标或下标列表。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.vote_poll(chat_id, message_id, options)

    @mcp.tool()
    @wrap_errors
    async def forward_message(
        ctx: Context,
        chat_id: int | str,
        from_chat_id: int | str,
        message_ids: int | list[int],
    ) -> dict:
        """转发消息(如把频道文章转发给 bot,测 bot 的转发处理)。
        message_ids:单条或列表;from_chat_id 与 chat_id 都需在白名单。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        from_chat_id = await resolve_chat_id(state.client, from_chat_id)
        require_chat(access, chat_id)
        require_chat(access, from_chat_id)
        return await state.client.forward_message(chat_id, from_chat_id, message_ids)

    @mcp.tool()
    @wrap_errors
    async def join_chat(ctx: Context, chat_id: int | str) -> dict:
        """加入群/频道(触发 bot 的 new_chat_members 更新)。
        chat_id 支持数字 id、@username、邀请链接(t.me/+xxx / t.me/joinchat/xxx)。
        邀请链接加入的新群不在白名单,加入后需将其加入白名单才能操作。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        s = str(chat_id).strip()
        if s.lstrip("-").isdigit():
            chat_id = int(s)
            require_chat(access, chat_id)
        elif not _is_invite_link(s):
            chat_id = await resolve_chat_id(state.client, chat_id)
            require_chat(access, chat_id)
        return await state.client.join_chat(chat_id)

    @mcp.tool()
    @wrap_errors
    async def leave_chat(ctx: Context, chat_id: int | str) -> dict:
        """退出群/频道(触发 bot 的 left_chat_member 更新)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.leave_chat(chat_id)

    @mcp.tool()
    @wrap_errors
    async def edit_message(ctx: Context, chat_id: int | str, message_id: int, text: str) -> dict:
        """编辑自己发送的消息。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.edit_message(chat_id, message_id, text)

    @mcp.tool()
    @wrap_errors
    async def delete_message(ctx: Context, chat_id: int | str, message_id: int) -> dict:
        """删除消息(双方可见,revoke)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.delete_message(chat_id, message_id)

    @mcp.tool()
    @wrap_errors
    async def send_chat_action(ctx: Context, chat_id: int | str, action: str = "typing") -> dict:
        """发送聊天动作(TYPING/UPLOAD_PHOTO 等,MTProto 层对 bot 可见)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_chat_action(chat_id, action)

    @mcp.tool()
    @wrap_errors
    async def click_inline_button(
        ctx: Context,
        chat_id: int | str,
        message_id: int,
        button_text: str | None = None,
        row_index: int = 0,
        col_index: int = 0,
        data: str | None = None,
    ) -> dict:
        """模拟用户点击 bot 消息上的 inline 按钮(触发 callback_query)。

        注意:这是"点击消息上的按钮",不是"发起 inline 查询"(向 bot 的 inline mode
        发查询请用 send_inline_query)。
        定位优先级:data(callback_data 原文,可从 get_messages 的 reply_markup 里拿到)
        > button_text(按钮文本)> row_index/col_index。
        url 按钮不触发点击,返回目标 URL;点击后 bot 的行为(编辑消息/新消息)
        可用 wait_for_update 或 get_chat_history 观察。
        """
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.click_inline_button(
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
        ctx: Context, chat_id: int | str, message_id: int, emoji: str, big: bool = False
    ) -> dict:
        """给消息发送 reaction(测试 bot 的 reaction 处理)。emoji 如 👍 ❤️ 🔥。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        chat_id = await resolve_chat_id(state.client, chat_id)
        require_chat(access, chat_id)
        return await state.client.send_reaction(chat_id, message_id, emoji, big=big)


def _is_invite_link(s: str) -> bool:
    """t.me/+xxx / t.me/joinchat/xxx 邀请链接。"""
    import re

    return re.match(r"(?:https?://)?(?:t|telegram)\.me/(?:\+|joinchat/)", s) is not None
