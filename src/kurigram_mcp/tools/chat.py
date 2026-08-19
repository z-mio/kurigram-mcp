"""聊天操作工具:发送/编辑/删除/动作。全部强制白名单校验。"""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer

from .common import ServerState, access_for, require_chat, wrap_errors


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @wrap_errors
    async def send_message(
        ctx: Context,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str = "none",
    ) -> dict:
        """发送文本消息。parse_mode: none | markdown | html。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        require_chat(access, chat_id)
        return await state.client.send_message(
            chat_id, text, reply_to_message_id=reply_to_message_id, parse_mode=parse_mode
        )

    @mcp.tool()
    @wrap_errors
    async def send_photo(
        ctx: Context,
        chat_id: int,
        media: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送图片。media:本地路径 | Telegram file_id | http(s) URL。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        require_chat(access, chat_id)
        return await state.client.send_photo(
            chat_id, media, caption=caption, reply_to_message_id=reply_to_message_id
        )

    @mcp.tool()
    @wrap_errors
    async def send_document(
        ctx: Context,
        chat_id: int,
        media: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送文件。media:本地路径 | Telegram file_id | http(s) URL。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        require_chat(access, chat_id)
        return await state.client.send_document(
            chat_id, media, caption=caption, reply_to_message_id=reply_to_message_id
        )

    @mcp.tool()
    @wrap_errors
    async def edit_message(ctx: Context, chat_id: int, message_id: int, text: str) -> dict:
        """编辑自己发送的消息。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        require_chat(access, chat_id)
        return await state.client.edit_message(chat_id, message_id, text)

    @mcp.tool()
    @wrap_errors
    async def delete_message(ctx: Context, chat_id: int, message_id: int) -> dict:
        """删除消息(双方可见,revoke)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        require_chat(access, chat_id)
        return await state.client.delete_message(chat_id, message_id)

    @mcp.tool()
    @wrap_errors
    async def send_chat_action(ctx: Context, chat_id: int, action: str = "typing") -> dict:
        """发送聊天动作(TYPING/UPLOAD_PHOTO 等,MTProto 层对 bot 可见)。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        require_chat(access, chat_id)
        return await state.client.send_chat_action(chat_id, action)

    @mcp.tool()
    @wrap_errors
    async def click_inline_button(
        ctx: Context,
        chat_id: int,
        message_id: int,
        button_text: str | None = None,
        row_index: int = 0,
        col_index: int = 0,
        data: str | None = None,
    ) -> dict:
        """模拟用户点击 bot 消息上的 inline 按钮(触发 callback_query)。

        定位优先级:data(callback_data 原文,可从 get_messages 的 reply_markup 里拿到)
        > button_text(按钮文本)> row_index/col_index。
        url 按钮不触发点击,返回目标 URL;点击后 bot 的行为(编辑消息/新消息)
        可用 wait_for_update 或 get_chat_history 观察。
        """
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
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
        ctx: Context, chat_id: int, message_id: int, emoji: str, big: bool = False
    ) -> dict:
        """给消息发送 reaction(测试 bot 的 reaction 处理)。emoji 如 👍 ❤️ 🔥。"""
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        require_chat(access, chat_id)
        return await state.client.send_reaction(chat_id, message_id, emoji, big=big)
