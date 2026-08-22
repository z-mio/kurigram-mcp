"""kurigram/pyrogram Client 生命周期封装。

注意:kurigram 2.2.24 的 PyPI 发行名是 kurigram,但导入名是 pyrogram
(drop-in 替换上游已停维护的 Pyrogram),因此这里统一 from pyrogram import Client。
"""

from __future__ import annotations

import random
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from loguru import logger
from pyrogram import Client
from pyrogram.enums import ChatAction, ParseMode
from pyrogram.errors import RPCError
from pyrogram.raw import functions

from ..config import Settings
from ..errors import INTERNAL, RPC, SESSION_INVALID, McpError, to_mcp_error
from .raw import build_value, resolve_function, to_plain
from .updates import EventBus
from .views import chat_view, inline_result_view, message_view, poll_view, user_view


def parse_proxy(url: str | None) -> dict | None:
    """把 socks5://user:pass@host:port 形式的配置转成 pyrogram proxy dict。"""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("socks5", "socks4", "http"):
        raise McpError(INTERNAL, f"不支持的代理协议: {parts.scheme}(支持 socks5/socks4/http)")
    return {
        "scheme": parts.scheme,
        "hostname": parts.hostname or "",
        "port": parts.port or 1080,
        "username": parts.username,
        "password": parts.password,
    }


def _find_large_ints(value, path: str = "") -> list[tuple[str, int]]:
    """递归查找参数中绝对值超过 2^53 的整数(JS 客户端 JSON 传输会丢精度)。"""
    found: list[tuple[str, int]] = []
    if isinstance(value, bool):
        return found
    if isinstance(value, int):
        if abs(value) >= 2**53:
            found.append((path or "<root>", value))
    elif isinstance(value, dict):
        for k, v in value.items():
            found.extend(_find_large_ints(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.extend(_find_large_ints(v, f"{path}[{i}]"))
    return found


def _coerce_numeric_strings(value):
    """把纯数字字符串(-?\\d+)转 int;JS 精度丢失场景下用户可用字符串传大整数。"""
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    if isinstance(value, dict):
        return {k: _coerce_numeric_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce_numeric_strings(v) for v in value]
    return value


def _has_numeric_strings(value) -> bool:
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return True
    if isinstance(value, dict):
        return any(_has_numeric_strings(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_numeric_strings(v) for v in value)
    return False


class TelegramClient:
    """管理 kurigram Client:启动前校验会话文件,避免误入交互式登录。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Client | None = None
        self.me = None
        self.bus = EventBus()

    @property
    def session_file(self) -> Path:
        return self.settings.session_file

    def _client_name(self) -> str:
        """pyrogram Client 名 = 会话文件名(与 session_file 保持一致)。"""
        return f"u_{self.settings.api_id}"
    @property
    def raw(self) -> Client:
        if self._client is None:
            raise McpError(SESSION_INVALID, "Telegram 会话未连接")
        return self._client

    @property
    def connected(self) -> bool:
        return self._client is not None and bool(getattr(self._client, "is_connected", False))

    async def start(self) -> None:
        """连接并校验会话;会话文件缺失时明确报错,绝不静默进入交互式登录。"""
        if not self.session_file.exists():
            raise McpError(
                SESSION_INVALID,
                f"未找到会话文件 {self.session_file};请先运行 `kurigram-mcp session add` 完成登录",
            )
        self.settings.require_credentials()
        self.settings.ensure_dirs()
        self._client = Client(
            self._client_name(),
            api_id=self.settings.api_id,
            api_hash=self.settings.api_hash,
            workdir=self.settings.sessions_dir,  # 会话文件位于 sessions/ 子目录
            proxy=parse_proxy(self.settings.proxy),
        )
        try:
            await self._client.start()
            self.me = await self._client.get_me()
            self._register_update_handlers()
        except McpError:
            raise
        except Exception as exc:
            raise to_mcp_error(exc) from exc

    def _register_update_handlers(self) -> None:
        """注册更新 handler -> 事件总线。handler 在客户端事件循环上执行。"""
        from pyrogram.handlers import (
            DeletedMessagesHandler,
            EditedMessageHandler,
            MessageHandler,
            MessageReactionHandler,
        )

        client = self._client
        if client is None:
            return

        async def on_message(_c, message) -> None:
            ts = getattr(message, "date", None)
            self.bus.push(
                "message",
                message.chat.id,
                message_view(message),
                ts=ts.timestamp() if ts else None,
            )

        async def on_edited(_c, message) -> None:
            ts = getattr(message, "edit_date", None) or getattr(message, "date", None)
            self.bus.push(
                "edited_message",
                message.chat.id,
                message_view(message),
                ts=ts.timestamp() if ts else None,
            )

        async def on_reaction(_c, reaction) -> None:
            new = getattr(reaction, "new_reaction", None)
            payload = {
                "chat_id": getattr(getattr(reaction, "chat", None), "id", None),
                "message_id": getattr(reaction, "message_id", None),
                "user": {
                    "id": getattr(getattr(reaction, "user", None), "id", None),
                    "username": getattr(getattr(reaction, "user", None), "username", None),
                    "is_bot": bool(getattr(getattr(reaction, "user", None), "is_bot", False)),
                },
                "emoji": getattr(new, "emoji", None),
                "custom_emoji_id": getattr(new, "custom_emoji_id", None),
            }
            ts = getattr(reaction, "date", None)
            self.bus.push(
                "reaction",
                payload["chat_id"],
                payload,
                ts=ts.timestamp() if ts else None,
            )

        async def on_deleted(_c, messages) -> None:
            for m in messages:
                self.bus.push(
                    "deleted_message",
                    m.chat.id,
                    {"chat_id": m.chat.id, "message_id": m.id},
                )

        client.add_handler(MessageHandler(on_message))
        client.add_handler(EditedMessageHandler(on_edited))
        client.add_handler(MessageReactionHandler(on_reaction))
        client.add_handler(DeletedMessagesHandler(on_deleted))
        logger.debug("更新 handler 已注册(消息/编辑/反应/删除)")

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.stop()
            except Exception as exc:  # noqa: BLE001 - 停止失败不影响进程退出
                logger.debug("关闭客户端时出错: {}", exc)
            self._client = None

    async def whoami(self) -> dict:
        if self._client is None or self.me is None:
            raise McpError(SESSION_INVALID, "Telegram 会话未连接")
        view = user_view(self.me)
        view["dc_id"] = getattr(getattr(self._client, "session", None), "dc_id", None)
        view["session_file"] = str(self.session_file)
        return view

    async def ping(self) -> float | None:
        """MTProto 往返延迟(ms);失败返回 None。"""
        if self._client is None:
            return None
        try:
            t0 = time.perf_counter()
            await self._client.invoke(functions.Ping(ping_id=random.randint(1, 2**31)))
            return round((time.perf_counter() - t0) * 1000, 1)
        except Exception:  # noqa: BLE001
            return None

    # ---------- 发送 ----------

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str = "none",
    ) -> dict:
        msg = await self.raw.send_message(
            chat_id,
            text,
            parse_mode=_parse_mode(parse_mode),
            reply_to_message_id=reply_to_message_id,
        )
        return message_view(msg)

    async def send_photo(
        self,
        chat_id: int,
        media: str,
        caption: str | None = None,
        parse_mode: str = "none",
        reply_to_message_id: int | None = None,
    ) -> dict:
        msg = await self.raw.send_photo(
            chat_id,
            media,
            caption=caption,
            parse_mode=_parse_mode(parse_mode),
            reply_to_message_id=reply_to_message_id,
        )
        return message_view(msg)

    async def send_document(
        self,
        chat_id: int,
        media: str,
        caption: str | None = None,
        parse_mode: str = "none",
        reply_to_message_id: int | None = None,
    ) -> dict:
        msg = await self.raw.send_document(
            chat_id,
            media,
            caption=caption,
            parse_mode=_parse_mode(parse_mode),
            reply_to_message_id=reply_to_message_id,
        )
        return message_view(msg)

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> dict:
        msg = await self.raw.edit_message_text(
            chat_id, message_id, text, parse_mode=_parse_mode("none")
        )
        return message_view(msg)

    async def delete_message(self, chat_id: int, message_id: int) -> dict:
        await self.raw.delete_messages(chat_id, message_id)
        return {"chat_id": chat_id, "deleted_message_id": message_id, "deleted": True}

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> dict:
        try:
            chat_action = ChatAction[action.upper()]
        except KeyError as exc:
            raise McpError(
                INTERNAL,
                f"不支持的 chat action: {action}(支持: {', '.join(a.name for a in ChatAction)})",
            ) from exc
        await self.raw.send_chat_action(chat_id, chat_action)
        return {"chat_id": chat_id, "action": chat_action.name, "sent": True}

    async def start_bot(self, bot_username: str, param: str = "") -> dict:
        """给 bot 发 /start(可带参),返回启动消息;自动解析 id 供白名单校验。"""
        chat = await self.raw.get_chat(bot_username)
        msg = await self.raw.start_bot(chat.id, param=param)
        return message_view(msg)

    async def click_inline_button(
        self,
        chat_id: int,
        message_id: int,
        button_text: str | None = None,
        row_index: int = 0,
        col_index: int = 0,
        data: str | None = None,
    ) -> dict:
        """模拟用户点击 inline 按钮(触发 callback_query)。

        定位优先级:data(callback_data 原文)> button_text(文本匹配)> row/col 下标。
        url 按钮返回目标 URL;callback 按钮触发点击;其他类型按钮返回类型说明。
        """
        from pyrogram.raw.functions.messages import GetBotCallbackAnswer
        from pyrogram.types import InlineKeyboardMarkup

        msg = await self.raw.get_messages(chat_id, message_id)
        if msg is None or not getattr(msg, "reply_markup", None):
            raise McpError("NO_BUTTONS", f"消息 {message_id} 没有按钮")
        markup = msg.reply_markup
        if not isinstance(markup, InlineKeyboardMarkup):
            raise McpError(
                "NO_BUTTONS",
                f"消息 {message_id} 的按钮类型: {type(markup).__name__};可点击类型为 InlineKeyboardMarkup",
            )

        # 定位按钮
        target = None
        if data is not None:
            for row in markup.inline_keyboard:
                for b in row:
                    cb = b.callback_data
                    cb_s = (
                        cb.decode("utf-8", errors="replace")
                        if isinstance(cb, bytes)
                        else str(cb or "")
                    )
                    if cb_s == data:
                        target = b
                        break
                if target:
                    break
        elif button_text:
            for row in markup.inline_keyboard:
                for b in row:
                    if b.text == button_text:
                        target = b
                        break
                if target:
                    break
        else:
            try:
                target = markup.inline_keyboard[row_index][col_index]
            except IndexError as exc:
                raise McpError(
                    "BUTTON_NOT_FOUND", f"按钮下标越界: row={row_index} col={col_index}"
                ) from exc

        if target is None:
            raise McpError(
                "BUTTON_NOT_FOUND",
                f"消息 {message_id} 上没有匹配的按钮(data={data!r} text={button_text!r})",
            )

        # url 按钮:直接返回目标 URL
        if getattr(target, "url", None):
            return {"type": "url", "text": target.text, "url": target.url}

        # 无 callback_data 的按钮(web_app/登录/支付等):返回类型说明
        if getattr(target, "callback_data", None) is None:
            kinds = [
                k
                for k in (
                    "web_app",
                    "login_url",
                    "switch_inline_query",
                    "switch_inline_query_current_chat",
                    "pay",
                    "user_id",
                )
                if getattr(target, k, None) is not None
            ]
            return {"type": "unsupported", "text": target.text, "button_type": kinds or "unknown"}

        # callback 按钮:触发点击
        cb = target.callback_data
        if isinstance(cb, str):
            cb = cb.encode()
        peer = await self.raw.resolve_peer(chat_id)
        try:
            result = await self.raw.invoke(
                GetBotCallbackAnswer(peer=peer, msg_id=message_id, data=cb, game=False)
            )
        except Exception as exc:
            # DATA_INVALID 常见于"按钮已被消耗/消息已被 bot 更新"——
            # 点击可能实际已生效,重新拉消息确认
            if "DATA_INVALID" in str(exc):
                fresh = await self.raw.get_messages(chat_id, message_id)
                old_edit = getattr(msg, "edit_date", None)
                new_edit = getattr(fresh, "edit_date", None) if fresh else None
                if fresh is not None and new_edit is not None and new_edit != old_edit:
                    return {
                        "type": "already_processed",
                        "text": target.text,
                        "note": "点击已生效:消息已被 bot 更新(按钮 data 失效属正常),"
                        "请重新获取消息查看新状态",
                        "message_edit_date": new_edit.isoformat() if new_edit else None,
                    }
            raise to_mcp_error(exc) from exc
        return {
            "type": "callback",
            "text": target.text,
            "alert": bool(result.alert),
            "has_url": bool(result.has_url),
            "message": getattr(result, "message", None),
            "url": getattr(result, "url", None),
            "cache_time": getattr(result, "cache_time", None),
        }

    async def send_reaction(
        self, chat_id: int, message_id: int, emoji: str, big: bool = False
    ) -> dict:
        """给消息发送 reaction(测试 bot 的 reaction 处理)。"""
        await self.raw.send_reaction(chat_id, message_id, emoji, big=big)
        return {
            "chat_id": chat_id,
            "message_id": message_id,
            "emoji": emoji,
            "big": big,
            "sent": True,
        }

    async def send_voice(
        self,
        chat_id: int,
        media: str,
        caption: str | None = None,
        parse_mode: str = "none",
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送语音。media:本地路径 | Telegram file_id | http(s) URL。"""
        msg = await self.raw.send_voice(
            chat_id,
            media,
            caption=caption or "",
            parse_mode=_parse_mode(parse_mode),
            reply_to_message_id=reply_to_message_id,
        )
        return message_view(msg)

    async def send_sticker(
        self, chat_id: int, media: str, reply_to_message_id: int | None = None
    ) -> dict:
        """发送贴纸。media:本地 .webp 路径 | Telegram file_id | http(s) URL。"""
        msg = await self.raw.send_sticker(chat_id, media, reply_to_message_id=reply_to_message_id)
        return message_view(msg)

    async def send_media_group(
        self,
        chat_id: int,
        media: list,
        reply_to_message_id: int | None = None,
    ) -> dict:
        """发送相册(媒体组)。media 为条目列表,每条:字符串(路径/file_id/URL)
        或 {"media": ..., "type": "photo"|"document"|"video"|"audio", "caption": ...}
        (type 缺省按扩展名推断,图片归 photo、其余归 document)。
        """
        from pyrogram.types import (
            InputMediaAudio,
            InputMediaDocument,
            InputMediaPhoto,
            InputMediaVideo,
        )

        _IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff")
        _MEDIA_CLS = {
            "photo": InputMediaPhoto,
            "document": InputMediaDocument,
            "video": InputMediaVideo,
            "audio": InputMediaAudio,
        }

        items = []
        for item in media:
            if isinstance(item, str):
                kind = "photo" if str(item).lower().endswith(_IMAGE_EXT) else "document"
                items.append(_MEDIA_CLS[kind](item))
            elif isinstance(item, dict):
                src = item.get("media")
                if not src:
                    raise McpError(INTERNAL, "media_group 条目需包含 media(路径/file_id/URL)")
                kind = item.get("type") or (
                    "photo" if str(src).lower().endswith(_IMAGE_EXT) else "document"
                )
                if kind not in _MEDIA_CLS:
                    raise McpError(
                        INTERNAL,
                        f"media_group 条目 type 不支持: {kind}(支持: {', '.join(_MEDIA_CLS)})",
                    )
                items.append(
                    _MEDIA_CLS[kind](
                        src,
                        caption=item.get("caption") or "",
                        parse_mode=_parse_mode(item.get("parse_mode", "none")),
                    )
                )
            else:
                raise McpError(INTERNAL, f"media_group 条目类型不支持: {type(item).__name__}")
        if not items:
            raise McpError(INTERNAL, "media_group 不能为空")
        msgs = await self.raw.send_media_group(
            chat_id, items, reply_to_message_id=reply_to_message_id
        )
        return {
            "count": len(msgs),
            "media_group_id": getattr(msgs[0], "media_group_id", None) if msgs else None,
            "messages": [message_view(m) for m in msgs],
        }

    async def send_poll(
        self,
        chat_id: int,
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
        """发送投票/测验。options 为选项文本列表;is_quiz 时可用 correct_option_id(0 基)+ explanation。"""
        from pyrogram.enums import PollType

        msg = await self.raw.send_poll(
            chat_id,
            question,
            options,
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers or None,
            allows_revoting=allows_revoting or None,
            type=PollType.QUIZ if is_quiz else PollType.REGULAR,
            correct_option_ids=[correct_option_id] if correct_option_id is not None else None,
            explanation=explanation,
            open_period=open_period,
        )
        return message_view(msg)

    async def vote_poll(self, chat_id: int, message_id: int, options: int | list[int]) -> dict:
        """投票(测试 bot 的 poll_answer 处理)。options:选项下标或下标列表。"""
        poll = await self.raw.vote_poll(chat_id, message_id, options)
        return poll_view(poll) or {}

    async def forward_message(
        self, chat_id: int, from_chat_id: int, message_ids: int | list[int]
    ) -> dict:
        """转发消息(如"把频道文章转发给 bot")。message_ids:单条或列表。"""
        ids = [message_ids] if isinstance(message_ids, int) else list(message_ids)
        msgs = await self.raw.forward_messages(chat_id, from_chat_id, ids)
        return {"count": len(msgs), "messages": [message_view(m) for m in msgs]}

    async def join_chat(self, chat_id: int | str) -> dict:
        """加入群/频道。支持数字 id、@username、邀请链接(t.me/+xxx / joinchat)。

        kurigram 返回 ChatJoinResult:成功时带 .chat;加入请求需审批/机器人验证时无 .chat。
        """
        result = await self.raw.join_chat(chat_id)
        chat = getattr(result, "chat", None)
        if chat is not None:
            view = chat_view(chat)
            view["members_count"] = getattr(chat, "members_count", None)
            return view
        return {
            "chat_id": chat_id,
            "status": type(result).__name__,
            "note": "加入请求已提交,需管理员审批/机器人验证后生效",
        }

    async def leave_chat(self, chat_id: int) -> dict:
        """退出群/频道。"""
        await self.raw.leave_chat(chat_id)
        return {"chat_id": chat_id, "left": True}

    async def get_chat_members_count(self, chat_id: int) -> dict:
        """群/频道成员数(用户/私聊场景下成员概念不存在)。"""
        count = await self.raw.get_chat_members_count(chat_id)
        return {"chat_id": chat_id, "members_count": count}

    async def send_inline_query(
        self, bot_username: str, query: str = "", offset: str = ""
    ) -> dict:
        """向 bot 发起 inline 查询(模拟用户在输入框输入 @bot query),返回 bot 的答案。

        Telegram 要求 bot 开启 inline mode;bot 10 秒不应答会超时。
        """
        try:
            results = await self.raw.get_inline_bot_results(bot_username, query=query, offset=offset)
        except TimeoutError:
            return {
                "timeout": True,
                "bot": bot_username,
                "query": query,
                "hint": "bot 10 秒内未应答 inline 查询(可能未开启 inline mode、查询处理慢或报错)",
            }
        switch_pm = getattr(results, "switch_pm", None)
        return {
            "bot": bot_username,
            "query": query,
            "offset": offset,
            "count": len(results.results or []),
            "gallery": bool(getattr(results, "gallery", False)),
            "cache_time": getattr(results, "cache_time", None),
            "next_offset": getattr(results, "next_offset", None) or "",
            "switch_pm": (
                {"text": getattr(switch_pm, "text", None), "start_param": getattr(switch_pm, "start_param", None)}
                if switch_pm is not None
                else None
            ),
            "results": [inline_result_view(r) for r in (results.results or [])],
        }


    # ---------- 读取 ----------

    async def get_chat(self, chat_id: int) -> dict:
        return chat_view(await self.raw.get_chat(chat_id))

    async def get_chat_history(
        self, chat_id: int, limit: int = 50, offset_id: int | None = None
    ) -> dict:
        messages = [
            message_view(m)
            async for m in self.raw.get_chat_history(chat_id, limit=limit, offset_id=offset_id)
        ]
        next_offset_id = messages[-1]["message_id"] if len(messages) == limit else None
        return {
            "chat_id": chat_id,
            "count": len(messages),
            "next_offset_id": next_offset_id,
            "messages": messages,
        }

    async def get_messages(self, chat_id: int, message_ids: list[int]) -> dict:
        msgs = await self.raw.get_messages(chat_id, message_ids)
        return {
            "chat_id": chat_id,
            "count": len(msgs),
            "messages": [message_view(m) for m in msgs if m is not None],
        }

    async def get_dialogs(self, allowed_ids: set[int]) -> dict:
        dialogs = []
        async for d in self.raw.get_dialogs():
            chat = d.chat
            if chat.id not in allowed_ids:
                continue
            dialogs.append(
                {
                    "chat_id": chat.id,
                    "type": str(chat.type.value) if chat.type else None,
                    "title": chat.title,
                    "username": chat.username,
                    "unread_count": getattr(d, "unread_messages_count", None),
                    "top_message_id": getattr(getattr(d, "top_message", None), "id", None),
                }
            )
        return {"count": len(dialogs), "dialogs": dialogs}

    async def search_messages(self, chat_id: int, query: str, limit: int = 20) -> dict:
        messages = [
            message_view(m) async for m in self.raw.search_messages(chat_id, query, limit=limit)
        ]
        return {
            "chat_id": chat_id,
            "query": query,
            "count": len(messages),
            "messages": messages,
        }

    async def bot_meta(self, bot_username: str) -> dict:
        """bot 元信息:inline placeholder / attach menu / 活跃用户数(容错,失败返回空)。

        resolveUsername 返回的 User 对象自带这些字段,无需 getFullUser。
        """
        from pyrogram.raw.functions import contacts

        try:
            resolved = await self.raw.invoke(
                contacts.ResolveUsername(username=bot_username.removeprefix("@"))
            )
            if not resolved.users:
                return {}
            u = resolved.users[0]
            return {
                "bot_inline_placeholder": getattr(u, "bot_inline_placeholder", None),
                "bot_attach_menu": bool(getattr(u, "bot_attach_menu", False)),
                "bot_active_users": getattr(u, "bot_active_users", None),
                "bot_can_edit": bool(getattr(u, "bot_can_edit", False)),
            }
        except Exception as exc:  # noqa: BLE001 - 探测失败不阻塞整体
            logger.debug("bot_meta 失败: {}", exc)
            return {}

    # ---------- 深度调试 ----------

    async def raw_invoke(self, function: str, params: dict) -> dict:
        """调用任意 raw MTProto 函数,直接执行你指定的函数(可含删除、修改账号设置等操作)。

        大整数检测:JS 客户端(如 DSH)以 JSON number 传输 64 位整数会丢精度
        (超过 2^53 的 access_hash/query_id 等),导致 BOT_INVALID/PEER_ID_INVALID
        等误导性错误——检测到即附加提示,并建议改用字符串传参。
        """
        cls = resolve_function(function)
        large = _find_large_ints(params)
        warning = None
        if large:
            shown = ", ".join(f"{p}={v}" for p, v in large[:5])
            warning = (
                f"参数含超过 2^53 的大整数({shown});若经 JS 客户端(如 DSH)传递,"
                "这些值可能已丢精度导致调用失败——失败时请改用字符串形式传参,"
                '如 access_hash 用 "-5882132225181774741"(raw_invoke 会按数字解析)'
            )
        try:
            result = await self.raw.invoke(cls(**build_value(params)))
        except McpError:
            raise
        except Exception as exc:
            # 纯数字字符串参数是 JS 精度丢失场景的字符串兜底写法:
            # 首次按字符串构建类型失败时,尝试按 int 解析重试
            if _has_numeric_strings(params):
                try:
                    result = await self.raw.invoke(
                        cls(**build_value(_coerce_numeric_strings(params)))
                    )
                except Exception as retry_exc:  # noqa: BLE001
                    # 重试已到 Telegram 层,其错误更接近真实原因;
                    # 首次的 to_bytes 等只是字符串序列化噪音,应替换掉(错误遮蔽修复)
                    if "to_bytes" in str(exc) or "not a valid int" in str(exc):
                        logger.debug("raw_invoke 数字字符串重试失败(替换原始错误): {}", retry_exc)
                        exc = retry_exc
                    else:
                        logger.debug("raw_invoke 数字字符串重试失败: {}", retry_exc)
                else:
                    return {
                        "function": function,
                        "result": to_plain(result),
                        "note": "已把纯数字字符串参数按整数解析(用于规避 JS 客户端大整数精度丢失)",
                    }
            msg = str(exc)
            # peer/实体类 RPC 错误 + 参数含大整数 -> 最可能是精度丢失,优先提示
            if large and isinstance(exc, RPCError):
                raise McpError(
                    RPC,
                    f"Telegram RPC 错误: {exc}\n提示: {warning}",
                    {"rpc_name": getattr(exc, "x", None), "precision_hint": True},
                ) from exc
            if "argument after ** must be a mapping" in msg:
                raise McpError(
                    INTERNAL,
                    f"raw 参数格式错误:嵌套对象作为具名参数的值传入,"
                    f'如 {{"peer": {{"_": "inputPeerEmpty"}}}};'
                    f'整个参数对象只包含 {function} 的具名参数,'
                    f'参数名与类型见 get_raw_method_info("{function}")',
                ) from exc
            m = re.search(r"missing (\d+) required keyword-only arguments: (.+)", msg)
            if m:
                raise McpError(
                    INTERNAL,
                    f"raw 函数 {function} 缺少 {m.group(1)} 个必填参数: {m.group(2)};"
                    f'请先 get_raw_method_info("{function}") 查询各参数类型后补全',
                ) from exc
            if (
                "has no attribute" in msg
                or "unexpected keyword" in msg
                or "required positional" in msg
                or "got an unexpected keyword" in msg
            ):
                raise McpError(
                    INTERNAL,
                    f"raw 参数与函数 {function} 的定义不匹配: {msg} "
                    f'——请先用 get_raw_method_info("{function}") 查询参数名与类型',
                ) from exc
            raise to_mcp_error(exc) from exc
        out = {"function": function, "result": to_plain(result)}
        if warning:
            out["warning"] = warning
        return out

    async def download_media(self, chat_id: int, message_id: int, path: str | None = None) -> dict:
        """下载消息媒体到本地路径,返回绝对路径与大小。

        path 缺省 → downloads/<chat_id>/<message_id>;
        相对路径 → 以 downloads_dir 为基准解析(2.2.25 起 pyrogram 会把相对路径
        解析到 workdir 即 sessions/ 目录,这里显式接管避免文件落错位置)。
        """
        msg = await self.raw.get_messages(chat_id, message_id)
        if msg is None or not getattr(msg, "media", None):
            raise McpError("NO_MEDIA", f"消息 {message_id} 没有媒体(或已被删除)")
        if path is None:
            path = str(self.settings.downloads_dir / str(chat_id) / str(message_id))
        else:
            p = Path(path)
            if not p.is_absolute():
                path = str(self.settings.downloads_dir / p)
        out = await self.raw.download_media(msg, file_name=path)
        if out is None:
            raise McpError("NO_MEDIA", f"消息 {message_id} 媒体下载失败")
        p = Path(out)
        return {"path": str(p.resolve()), "size_bytes": p.stat().st_size}


def _parse_mode(parse_mode: str | None):
    """'none' | 'markdown' | 'html' -> pyrogram ParseMode;None 保持客户端默认。

    注:parse_mode 支持 none/markdown/html 三种;需要剧透/下划线等格式时
    使用 HTML 的 <tg-spoiler> 表达。
    """
    if parse_mode is None:
        return None
    key = parse_mode.upper()
    if key == "NONE":
        return ParseMode.DISABLED
    try:
        return ParseMode[key]
    except KeyError as exc:
        raise McpError(
            INTERNAL, f"不支持的 parse_mode: {parse_mode}(支持: none/markdown/html)"
        ) from exc
