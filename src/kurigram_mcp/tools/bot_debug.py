"""Bot 调试工具:事件等待、事件流、启动 bot。

所有工具支持 account 参数:指定操作账号(缺省用服务器默认账号);
事件总线按账号隔离,wait/expect_silent/drain 只看到该账号的事件。
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable, Sequence
from typing import Literal

from loguru import logger
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from ..telegram.updates import BusEvent, event_view
from .common import (
    ServerState,
    access_for,
    require_chat,
    resolve_chat_id,
    wrap_errors,
)

EventTypeArg = Literal["message", "edited_message", "reaction", "deleted_message"]
_READ_ONLY = ToolAnnotations(read_only_hint=True)


def build_predicate(
    chat_id: int,
    from_bot: bool | None = None,
    text_contains: str | None = None,
    text_matches: str | None = None,
    types: Sequence[str] | None = None,
    reply_to_message_id: int | None = None,
    is_media: bool | None = None,
    media_type: str | None = None,
    after_seq: int | None = None,
    message_thread_id: int | None = None,
) -> Callable[[BusEvent], bool]:
    """构造事件匹配谓词(导出以便单测)。

    is_media: True=必须有媒体, False=必须无媒体;
    media_type: 媒体类型精确匹配(photo/voice/document/sticker/video/animation 等,
    与 get_messages 返回的 media 字段一致);
    text_matches: 正则匹配消息文本(re.search),用于金额/手机号/UUID 等格式断言;
    after_seq: 只匹配 seq 大于该值的事件(传上次返回的 event.seq,避免 lookback
    窗口内旧事件被连续等待重复匹配);
    message_thread_id: 只匹配指定论坛话题 ID 的消息事件。
    """

    def pred(ev: BusEvent) -> bool:
        if after_seq is not None and ev.seq <= after_seq:
            return False
        if ev.chat_id != chat_id:
            return False
        if types and ev.type not in types:
            return False
        if message_thread_id is not None and ev.payload.get("message_thread_id") != message_thread_id:
            return False
        if from_bot is not None:
            is_bot = False
            if ev.type in ("message", "edited_message"):
                is_bot = bool((ev.payload.get("from") or {}).get("is_bot"))
            if is_bot != from_bot:
                return False
        # 富消息(guest bot AI 回复)正文在 payload.rich.text,与 text 一并参与匹配
        text = ev.payload.get("text") or (ev.payload.get("rich") or {}).get("text") or ""
        if text_contains is not None and text_contains not in text:
            return False
        if text_matches is not None:
            try:
                if re.search(text_matches, text) is None:
                    return False
            except re.error:
                return False
        if is_media is not None:
            has = bool(ev.payload.get("media"))
            if has != is_media:
                return False
        if media_type is not None and ev.payload.get("media") != media_type:
            return False
        return reply_to_message_id is None or ev.payload.get("reply_to_message_id") == reply_to_message_id

    return pred


def register(mcp: MCPServer[ServerState]) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def wait_for_update(
        ctx: Context[ServerState],
        chat_id: int | str,
        timeout: float = 60,
        from_bot: bool | None = None,
        text_contains: str | None = None,
        text_matches: str | None = None,
        types: list[EventTypeArg] | None = None,
        reply_to_message_id: int | None = None,
        is_media: bool | None = None,
        media_type: str | None = None,
        after_seq: int | None = None,
        lookback_seconds: float = 60,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """等待匹配事件(默认含 60s lookback 覆盖 bot 快回复竞态)。
        谓词:from_bot/text_contains(含 rich.text)/text_matches(正则)/is_media/
        media_type(photo|video|document|audio|voice|sticker|animation|dice|poll|checklist|location|contact)/
        message_thread_id/reply_to_message_id(bot 回复常不引用,等任意回复用 from_bot=true)。
        连续等待传上次 event.seq(与 drain_updates.cursor 同序)到 after_seq;matched=false 时用 get_chat_history 查证。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        start = time.time()
        ev = await client.bus.wait(
            build_predicate(
                chat_id,
                from_bot,
                text_contains,
                text_matches,
                types,
                reply_to_message_id,
                is_media,
                media_type,
                after_seq,
                message_thread_id=message_thread_id,
            ),
            timeout=timeout,
            lookback_seconds=lookback_seconds,
        )
        waited = round(time.time() - start, 2)
        if ev is None:
            hint = f"用 get_chat_history 验证历史,或 drain_updates(cursor={client.bus.latest_seq}) 拉取后续事件"
            out: dict = {
                "matched": False,
                "timeout": True,
                "waited_seconds": waited,
                "hint": hint,
            }
            if client.bus.latest_seq == 0:
                # 进程启动以来零事件:可能事件流异常,或目标 chat 确实静默(事件总线只收他人消息)
                out["event_stream_idle"] = True
                out["hint"] = (
                    hint + ";事件总线记录他人/bot 的消息;自己发送的消息由发送工具直接返回,"
                    "请等 bot/他人消息,或用 get_chat_history 查证"
                )
            return out
        return {"matched": True, "waited_seconds": waited, "event": event_view(ev)}

    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def expect_silent(
        ctx: Context[ServerState],
        chat_id: int | str,
        duration: float = 5,
        from_bot: bool | None = None,
        types: list[EventTypeArg] | None = None,
        text_contains: str | None = None,
        text_matches: str | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """静默断言:等待 duration 秒确认无匹配事件(只看调用后的新事件)。
        返回 {silent, duration_seconds, count, events}。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        start_seq = client.bus.latest_seq
        start = time.time()
        await asyncio.sleep(duration)
        pred = build_predicate(
            chat_id,
            from_bot,
            text_contains,
            text_matches,
            types,
            message_thread_id=message_thread_id,
        )
        _, events = client.bus.drain(start_seq, chat_id=chat_id)
        matched = [e for e in events if pred(e)]
        return {
            "silent": len(matched) == 0,
            "duration_seconds": round(time.time() - start, 2),
            "count": len(matched),
            "events": [event_view(e) for e in matched],
        }

    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def drain_updates(
        ctx: Context[ServerState],
        cursor: int | None = None,
        chat_id: int | str | None = None,
        limit: int = 100,
        account: str | None = None,
    ) -> dict:
        """从 cursor(与 wait_for_update 的 event.seq 同序)增量拉取事件流。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        if chat_id is not None:
            access = access_for(state, account)
            chat_id = await resolve_chat_id(client, chat_id)
            require_chat(access, chat_id)
        new_cursor, events = client.bus.drain(cursor, chat_id=chat_id, limit=limit)
        return {
            "cursor": new_cursor,
            "count": len(events),
            "events": [event_view(e) for e in events],
        }

    @mcp.tool()
    @wrap_errors
    async def start_bot(
        ctx: Context[ServerState], bot_username: str, param: str = "", account: str | None = None
    ) -> dict:
        """向 bot 发 /start(param 为深链 payload)。
        bot 回复用 wait_for_update(from_bot=true) 或 get_chat_history 查看。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        chat_id = await client.resolve_chat_id(bot_username)
        access = access_for(state, account)
        require_chat(access, chat_id)
        return await client.start_bot(bot_username, param=param)

    @mcp.tool(annotations=_READ_ONLY)
    @wrap_errors
    async def send_inline_query(
        ctx: Context[ServerState],
        bot_username: str,
        query: str = "",
        offset: str = "",
        account: str | None = None,
    ) -> dict:
        """向 bot 发起 inline 查询(@bot query),返回 query_id 与候选结果列表(bot 需开启 inline mode)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        chat_id = await client.resolve_chat_id(bot_username)
        access = access_for(state, account)
        require_chat(access, chat_id)
        return await client.send_inline_query(bot_username, query=query, offset=offset)

    @mcp.tool()
    @wrap_errors
    async def send_inline_bot_result(
        ctx: Context[ServerState],
        chat_id: int | str,
        query_id: int | str,
        result_id: str,
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        account: str | None = None,
    ) -> dict:
        """选中并发送一条 inline 查询结果(触发 bot 的 chosen_inline_result)。
        query_id 与 result_id 来自 send_inline_query 返回值;目标 chat_id 需在白名单。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        cid = await resolve_chat_id(client, chat_id)
        require_chat(access, cid)
        return await client.send_inline_bot_result(
            cid,
            query_id,
            result_id,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    @mcp.tool()
    @wrap_errors
    async def probe_bot(
        ctx: Context[ServerState],
        bot_username: str,
        wait_per_command: float = 2.0,
        account: str | None = None,
    ) -> dict:
        """探测 bot 能力画像:拉资料/元信息并实际向 bot 发送 /start、/help、/menu 汇总回复(有发送副作用;需在白名单)。"""
        state = ctx.request_context.lifespan_context
        client = state.resolve(account)
        chat_id = await client.resolve_chat_id(bot_username)
        access = access_for(state, account)
        require_chat(access, chat_id)
        meta = await client.bot_meta(bot_username)
        start_seq = client.bus.latest_seq

        cmds: list[str] = []
        try:
            await client.start_bot(bot_username)
            cmds.append("/start")
        except Exception as exc:  # noqa: BLE001 - 单个命令失败继续探测
            logger.warning("probe_bot /start 失败: {}", exc)
        await asyncio.sleep(wait_per_command)
        for cmd in ("/help", "/menu"):
            try:
                await client.send_message(chat_id, cmd)
                cmds.append(cmd)
            except Exception as exc:  # noqa: BLE001
                logger.warning("probe_bot {} 失败: {}", cmd, exc)
            await asyncio.sleep(wait_per_command)

        # 收集 bot 回复:事件总线优先,历史兜底
        _, events = client.bus.drain(start_seq, chat_id=chat_id)
        replies = [e.payload for e in events if e.type == "message" and (e.payload.get("from") or {}).get("is_bot")]
        attribution = "event_bus"
        if not replies and cmds:
            hist = await client.get_chat_history(chat_id, limit=20)
            replies = [
                m
                for m in hist["messages"]
                if m.get("from", {}).get("is_bot") and (m.get("text") is not None or m.get("rich") is not None)
            ]
            replies = list(reversed(replies))[: len(cmds)]
            attribution = "history_fallback(顺序可能不精确)"

        out: dict = {}
        for i, cmd in enumerate(cmds):
            if i < len(replies):
                p = replies[i]
                out[cmd] = {
                    "text": p.get("text") or (p.get("rich") or {}).get("text"),
                    "media": p.get("media"),
                    "has_buttons": bool(p.get("reply_markup")) or bool((p.get("rich") or {}).get("buttons")),
                    "links": p.get("links"),
                }
            else:
                out[cmd] = None  # 静默无回复
        return {
            "bot_username": bot_username,
            "chat_id": chat_id,
            "profile": await client.get_chat(chat_id),
            **meta,
            "commands_sent": cmds,
            "replies": out,
            "attribution": attribution,
        }
