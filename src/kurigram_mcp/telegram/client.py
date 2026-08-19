"""kurigram/pyrogram Client 生命周期封装。

注意:kurigram 2.2.24 的 PyPI 发行名是 kurigram,但导入名是 pyrogram
(drop-in 替换上游已停维护的 Pyrogram),因此这里统一 from pyrogram import Client。
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from urllib.parse import urlsplit

from loguru import logger
from pyrogram import Client
from pyrogram.enums import ChatAction, ParseMode
from pyrogram.raw import functions

from ..config import Settings
from ..errors import INTERNAL, SESSION_INVALID, McpError, to_mcp_error
from .raw import build_value, resolve_function, to_plain
from .updates import EventBus
from .views import chat_view, message_view, user_view


def parse_proxy(url: str | None) -> dict | None:
    """把 socks5://user:pass@host:port 形式的配置转成 pyrogram proxy dict。"""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("socks5", "socks4", "http"):
        raise McpError("INTERNAL", f"不支持的代理协议: {parts.scheme}(支持 socks5/socks4/http)")
    return {
        "scheme": parts.scheme,
        "hostname": parts.hostname or "",
        "port": parts.port or 1080,
        "username": parts.username,
        "password": parts.password,
    }


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
        return f"u_{self.settings.api_id}" if self.settings.api_id else self.settings.session_name

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
                f"未找到会话文件 {self.session_file};请先运行 `kurigram-mcp auth` 完成登录",
            )
        self.settings.require_credentials()
        self.settings.ensure_dirs()
        self._client = Client(
            self._client_name(),
            api_id=self.settings.api_id,
            api_hash=self.settings.api_hash,
            workdir=self.settings.session_dir,
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
        reply_to_message_id: int | None = None,
    ) -> dict:
        msg = await self.raw.send_photo(
            chat_id,
            media,
            caption=caption,
            parse_mode=_parse_mode("none"),
            reply_to_message_id=reply_to_message_id,
        )
        return message_view(msg)

    async def send_document(
        self,
        chat_id: int,
        media: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        msg = await self.raw.send_document(
            chat_id,
            media,
            caption=caption,
            parse_mode=_parse_mode("none"),
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
        url 按钮不触发点击,返回目标 URL;非 callback 类型按钮返回类型说明。
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
                f"消息 {message_id} 不是 inline 按钮(类型: {type(markup).__name__})",
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

        # url 按钮:不触发点击
        if getattr(target, "url", None):
            return {"type": "url", "text": target.text, "url": target.url}

        # 非 callback 类型按钮
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

        # 触发点击
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

    # ---------- 深度调试 ----------

    async def raw_invoke(self, function: str, params: dict) -> dict:
        """调用任意 raw MTProto 函数(不做白名单/安全过滤)。"""
        cls = resolve_function(function)
        try:
            result = await self.raw.invoke(cls(**build_value(params)))
        except McpError:
            raise
        except Exception as exc:
            msg = str(exc)
            if (
                "has no attribute" in msg
                or "unexpected keyword" in msg
                or "required positional" in msg
            ):
                raise McpError(
                    INTERNAL,
                    f"raw 参数与函数 {function} 的定义不匹配: {msg} "
                    f'——请先用 get_raw_method_info("{function}") 查询参数名与类型',
                ) from exc
            raise to_mcp_error(exc) from exc
        return {"function": function, "result": to_plain(result)}

    async def download_media(self, chat_id: int, message_id: int, path: str | None = None) -> dict:
        """下载消息媒体到本地路径,返回绝对路径与大小。"""
        msg = await self.raw.get_messages(chat_id, message_id)
        if msg is None or not getattr(msg, "media", None):
            raise McpError("NO_MEDIA", f"消息 {message_id} 没有媒体(或已被删除)")
        if path is None:
            path = str(self.settings.downloads_dir / str(chat_id) / str(message_id))
        out = await self.raw.download_media(msg, file_name=path)
        if out is None:
            raise McpError("NO_MEDIA", f"消息 {message_id} 媒体下载失败")
        p = Path(out)
        return {"path": str(p.resolve()), "size_bytes": p.stat().st_size}


def _parse_mode(parse_mode: str | None):
    """'none' | 'markdown' | 'html' -> pyrogram ParseMode;None 保持客户端默认。"""
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
