"""Bot 调试工具:事件等待、事件流、启动 bot。"""

from __future__ import annotations

import time

from mcp.server.mcpserver import Context, MCPServer

from ..telegram.updates import BusEvent, event_view
from .common import ServerState, access_for, require_chat, wrap_errors


def build_predicate(
    chat_id: int,
    from_bot: bool | None = None,
    text_contains: str | None = None,
    types: list[str] | None = None,
    reply_to_message_id: int | None = None,
):
    """构造事件匹配谓词(导出以便单测)。"""

    def pred(ev: BusEvent) -> bool:
        if ev.chat_id != chat_id:
            return False
        if types and ev.type not in types:
            return False
        if from_bot is not None:
            is_bot = False
            if ev.type in ("message", "edited_message"):
                is_bot = bool((ev.payload.get("from") or {}).get("is_bot"))
            if is_bot != from_bot:
                return False
        if text_contains is not None and text_contains not in (ev.payload.get("text") or ""):
            return False
        return (
            reply_to_message_id is None
            or ev.payload.get("reply_to_message_id") == reply_to_message_id
        )

    return pred


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @wrap_errors
    async def wait_for_update(
        ctx: Context,
        chat_id: int,
        timeout: float = 60,
        from_bot: bool | None = None,
        text_contains: str | None = None,
        types: list[str] | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        """等待 chat 的新事件(默认含 5 秒 lookback,避免事件先到)。

        谓词:from_bot(是否 bot 发送)、text_contains(文本包含)、
        types(["message","edited_message","reaction","deleted_message"])、
        reply_to_message_id(回复哪条消息)。超时返回 matched=false。
        响应延迟 = 事件 payload.date - 你发送消息的 date。

        注意:bot 直接回复的消息通常没有 reply_to_message_id(Telegram 不强制引用),
        用 reply_to_message_id 谓词会漏匹配导致误判"没回复";只等"bot 回了任何消息"
        时用 from_bot=true 即可,需要精确匹配时配合 text_contains 或查历史确认。
        """
        state: ServerState = ctx.request_context.lifespan_context
        access = await access_for(ctx, state)
        require_chat(access, chat_id)
        start = time.time()
        ev = await state.bus.wait(
            build_predicate(chat_id, from_bot, text_contains, types, reply_to_message_id),
            timeout=timeout,
        )
        waited = round(time.time() - start, 2)
        if ev is None:
            return {"matched": False, "timeout": True, "waited_seconds": waited}
        return {"matched": True, "waited_seconds": waited, "event": event_view(ev)}

    @mcp.tool()
    @wrap_errors
    async def drain_updates(
        ctx: Context,
        cursor: int | None = None,
        chat_id: int | None = None,
        limit: int = 100,
    ) -> dict:
        """从光标处拉取事件流。cursor 单调递增:把返回的 cursor 传给下次调用即可增量拉取。"""
        state: ServerState = ctx.request_context.lifespan_context
        if chat_id is not None:
            access = await access_for(ctx, state)
            require_chat(access, chat_id)
        new_cursor, events = state.bus.drain(cursor, chat_id=chat_id, limit=limit)
        return {
            "cursor": new_cursor,
            "count": len(events),
            "events": [event_view(e) for e in events],
        }

    @mcp.tool()
    @wrap_errors
    async def start_bot(ctx: Context, bot_username: str, param: str = "") -> dict:
        """向 bot 发送 /start(可带参数),返回启动消息(需 bot 在白名单)。"""
        state: ServerState = ctx.request_context.lifespan_context
        chat = await state.client.raw.get_chat(bot_username)
        access = await access_for(ctx, state)
        require_chat(access, chat.id)
        return await state.client.start_bot(bot_username, param=param)
