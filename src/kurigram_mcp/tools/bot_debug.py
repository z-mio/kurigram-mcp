"""Bot 调试工具:事件等待、事件流、启动 bot。

所有工具支持 account 参数:指定操作账号(缺省用服务器默认账号);
事件总线按账号隔离,wait/expect_silent/drain 只看到该账号的事件。
"""

from __future__ import annotations

import asyncio
import re
import time

from loguru import logger
from mcp.server.mcpserver import Context, MCPServer

from ..telegram.updates import BusEvent, event_view
from .common import (
    ServerState,
    access_for,
    require_chat,
    resolve_chat_id,
    wrap_errors,
)


def build_predicate(
    chat_id: int,
    from_bot: bool | None = None,
    text_contains: str | None = None,
    text_matches: str | None = None,
    types: list[str] | None = None,
    reply_to_message_id: int | None = None,
    is_media: bool | None = None,
    media_type: str | None = None,
    after_seq: int | None = None,
):
    """构造事件匹配谓词(导出以便单测)。

    is_media: True=必须有媒体, False=必须无媒体;
    media_type: 媒体类型精确匹配(photo/voice/document/sticker/video/animation 等,
    与 get_messages 返回的 media 字段一致);
    text_matches: 正则匹配消息文本(re.search),用于金额/手机号/UUID 等格式断言;
    after_seq: 只匹配 seq 大于该值的事件(传上次返回的 event.seq,避免 lookback
    窗口内旧事件被连续等待重复匹配)。
    """

    def pred(ev: BusEvent) -> bool:
        if after_seq is not None and ev.seq <= after_seq:
            return False
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
        text = ev.payload.get("text") or ""
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
        chat_id: int | str,
        timeout: float = 60,
        from_bot: bool | None = None,
        text_contains: str | None = None,
        text_matches: str | None = None,
        types: list[str] | None = None,
        reply_to_message_id: int | None = None,
        is_media: bool | None = None,
        media_type: str | None = None,
        after_seq: int | None = None,
        lookback_seconds: float = 60,
        account: str | None = None,
    ) -> dict:
        """等待 chat 的新事件(默认含 60 秒 lookback,覆盖"bot 同秒回复、事件先到"的竞态;
        LLM 客户端两次工具调用间隔常达数秒~数十秒,太小的窗口会把快回复滑出去)。
        chat_id 支持数字/@username/me,可从 get_dialogs 或 get_chat 获取。

        谓词:from_bot(是否 bot 发送)、text_contains(文本包含)、
        text_matches(正则匹配,如 r"\\d+\\.\\d+ CNY" 断言金额格式)、
        types(["message","edited_message","reaction","deleted_message"])、
        reply_to_message_id(回复哪条消息)、is_media(是否带媒体)、
        media_type(媒体类型精确匹配,如 photo/voice/document/sticker/video)。
        超时返回 matched=false。
        返回字段:waited_seconds=本次等待实际耗时(事件可能在调用前已到达,此时为 0,
        不代表没等到);event.age_ms=事件年龄(距现在毫秒,用于判断回复快慢)。
        响应延迟 = 事件 payload.date - 你发送消息的 date。

        注意 1:bot 直接回复的消息通常没有 reply_to_message_id(Telegram 不强制引用),
        用 reply_to_message_id 谓词会漏匹配导致误判"没回复";只等"bot 回了任何消息"
        时用 from_bot=true 即可。

        注意 2:连续等待时把上次返回的 event.seq 传给 after_seq,可跳过 lookback
        窗口内的旧事件,避免把 bot 的旧回复误当新回复(子会话实测踩坑)。

        注意 3:wait 只覆盖"调用后入队 + lookback 窗口内已入队"的事件。matched=false
        不代表 bot 没回复——先用 get_chat_history 查证(回复一定在历史里),或按返回的
        hint 用 drain_updates(cursor) 增量拉取,再下结论。
        """
        state: ServerState = ctx.request_context.lifespan_context
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
            ),
            timeout=timeout,
            lookback_seconds=lookback_seconds,
        )
        waited = round(time.time() - start, 2)
        if ev is None:
            return {
                "matched": False,
                "timeout": True,
                "waited_seconds": waited,
                "hint": f"用 get_chat_history 验证历史,或 drain_updates(cursor={client.bus.latest_seq}) 拉取后续事件",
            }
        return {"matched": True, "waited_seconds": waited, "event": event_view(ev)}

    @mcp.tool()
    @wrap_errors
    async def expect_silent(
        ctx: Context,
        chat_id: int | str,
        duration: float = 5,
        from_bot: bool | None = None,
        types: list[str] | None = None,
        text_contains: str | None = None,
        text_matches: str | None = None,
        account: str | None = None,
    ) -> dict:
        """静默断言:等待 duration 秒,期间是否出现匹配事件(默认只看调用后的事件,不看历史)。

        与 wait_for_update 互补:wait 等"有回复",expect_silent 断言"无动静"——
        测 bot 对某输入静默无响应(功能未实现/权限拒绝/限流静默等)。
        例:发送 /menu 后 expect_silent(from_bot=true, duration=5),silent=true 即确认 bot 没回。

        谓词与 wait_for_update 相同(from_bot/types/text_contains/text_matches)。
        返回 {silent, duration_seconds, count, events}。
        """
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        access = access_for(state, account)
        chat_id = await resolve_chat_id(client, chat_id)
        require_chat(access, chat_id)
        start_seq = client.bus.latest_seq
        start = time.time()
        await asyncio.sleep(duration)
        pred = build_predicate(
            chat_id, from_bot, text_contains, text_matches, types
        )
        _, events = client.bus.drain(start_seq, chat_id=chat_id)
        matched = [e for e in events if pred(e)]
        return {
            "silent": len(matched) == 0,
            "duration_seconds": round(time.time() - start, 2),
            "count": len(matched),
            "events": [event_view(e) for e in matched],
        }

    @mcp.tool()
    @wrap_errors
    async def drain_updates(
        ctx: Context,
        cursor: int | None = None,
        chat_id: int | str | None = None,
        limit: int = 100,
        account: str | None = None,
    ) -> dict:
        """从光标处拉取事件流。cursor 单调递增:把返回的 cursor 传给下次调用即可增量拉取。chat_id 支持数字/@username/me(可从 get_dialogs 获取)。"""
        state: ServerState = ctx.request_context.lifespan_context
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
        ctx: Context, bot_username: str, param: str = "", account: str | None = None
    ) -> dict:
        """向 bot 发送 /start,触发 bot 的 start 流程。param 为 Telegram 深链 start 参数(等价于 "/start 后跟的 payload",如 param="menu" 对应 /start menu),不体现在消息文本中。返回的是你发出的 /start 消息(不是 bot 的回复);bot 的回复请用 wait_for_update(from_bot=true) 或 get_chat_history 查看。需 bot 在白名单。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        chat = await client.raw.get_chat(bot_username)
        access = access_for(state, account)
        require_chat(access, chat.id)
        return await client.start_bot(bot_username, param=param)

    @mcp.tool()
    @wrap_errors
    async def send_inline_query(
        ctx: Context,
        bot_username: str,
        query: str = "",
        offset: str = "",
        account: str | None = None,
    ) -> dict:
        """向 bot 发起 inline 查询(模拟用户在输入框输入 @bot query),返回 bot 的答案。

        Telegram 要求 bot 开启 inline mode;bot 10 秒不应答返回 timeout=true。
        bot 需在白名单。"""
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        chat = await client.raw.get_chat(bot_username)
        access = access_for(state, account)
        require_chat(access, chat.id)
        return await client.send_inline_query(bot_username, query=query, offset=offset)

    @mcp.tool()
    @wrap_errors
    async def probe_bot(
        ctx: Context,
        bot_username: str,
        wait_per_command: float = 2.0,
        account: str | None = None,
    ) -> dict:
        """探测 bot 能力画像(新 bot 接入测试的前置冒烟)。

        自动完成:资料(标题/类型/描述/成员数)+ bot 元信息(inline placeholder /
        attach menu / 活跃用户数)+ 命令回复行为(/start /help /menu 各等
        wait_per_command 秒,记录回复文本/媒体/按钮)。
        只读 + 3 条命令交互;bot 需在白名单。
        """
        state: ServerState = ctx.request_context.lifespan_context
        client = state.resolve(account)
        chat = await client.raw.get_chat(bot_username)
        access = access_for(state, account)
        require_chat(access, chat.id)
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
                await client.send_message(chat.id, cmd)
                cmds.append(cmd)
            except Exception as exc:  # noqa: BLE001
                logger.warning("probe_bot {} 失败: {}", cmd, exc)
            await asyncio.sleep(wait_per_command)

        # 收集 bot 回复:事件总线优先,历史兜底
        _, events = client.bus.drain(start_seq, chat_id=chat.id)
        replies = [
            e.payload
            for e in events
            if e.type == "message" and (e.payload.get("from") or {}).get("is_bot")
        ]
        attribution = "event_bus"
        if not replies and cmds:
            hist = await client.get_chat_history(chat.id, limit=20)
            replies = [
                m
                for m in hist["messages"]
                if m.get("from", {}).get("is_bot") and m.get("text") is not None
            ]
            replies = list(reversed(replies))[: len(cmds)]
            attribution = "history_fallback(顺序可能不精确)"

        out: dict = {}
        for i, cmd in enumerate(cmds):
            if i < len(replies):
                p = replies[i]
                out[cmd] = {
                    "text": p.get("text"),
                    "media": p.get("media"),
                    "has_buttons": bool(p.get("reply_markup")),
                    "links": p.get("links"),
                }
            else:
                out[cmd] = None  # 静默无回复
        return {
            "bot_username": bot_username,
            "chat_id": chat.id,
            "profile": await client.get_chat(chat.id),
            **meta,
            "commands_sent": cmds,
            "replies": out,
            "attribution": attribution,
        }
