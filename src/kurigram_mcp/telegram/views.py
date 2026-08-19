"""Telegram 对象 -> 扁平 JSON 的序列化视图。"""

from __future__ import annotations


def user_view(user) -> dict:
    """pyrogram User -> 扁平 dict(缺字段容错)。"""
    fields = (
        "id",
        "is_bot",
        "is_verified",
        "is_restricted",
        "is_scam",
        "is_fake",
        "first_name",
        "last_name",
        "username",
        "language_code",
        "dc_id",
    )
    return {f: getattr(user, f, None) for f in fields}


def chat_view(chat) -> dict:
    """pyrogram Chat -> 扁平 dict。"""
    fields = (
        "id",
        "type",
        "title",
        "username",
        "first_name",
        "last_name",
        "is_bot",
        "is_verified",
        "is_restricted",
        "is_scam",
        "is_fake",
        "description",
        "members_count",
        "photo",
    )
    return {f: getattr(chat, f, None) for f in fields}


def user_ref(user) -> dict | None:
    """消息中的发送者摘要。"""
    if user is None:
        return None
    return {
        "id": getattr(user, "id", None),
        "username": getattr(user, "username", None),
        "first_name": getattr(user, "first_name", None),
        "is_bot": bool(getattr(user, "is_bot", False)),
    }


def _button_view(btn) -> dict:
    """InlineKeyboardButton -> 扁平 dict。"""
    out: dict = {"text": btn.text}
    cb = getattr(btn, "callback_data", None)
    if cb is not None:
        out["callback_data"] = (
            cb.decode("utf-8", errors="replace") if isinstance(cb, bytes) else str(cb)
        )
    if getattr(btn, "url", None):
        out["url"] = btn.url
    web_app = getattr(btn, "web_app", None)
    if web_app is not None:
        out["web_app"] = getattr(web_app, "url", None)
    if getattr(btn, "user_id", None):
        out["user_id"] = btn.user_id
    if getattr(btn, "switch_inline_query", None) is not None:
        out["switch_inline_query"] = btn.switch_inline_query
    if getattr(btn, "pay", False):
        out["pay"] = True
    return out


def markup_view(markup) -> dict | None:
    """reply_markup -> 扁平 dict(按钮文本 + callback_data/url)。"""
    if markup is None:
        return None
    from pyrogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

    if isinstance(markup, InlineKeyboardMarkup):
        return {
            "type": "inline",
            "rows": [[_button_view(b) for b in row] for row in markup.inline_keyboard],
        }
    if isinstance(markup, ReplyKeyboardMarkup):
        return {
            "type": "reply",
            "rows": [[{"text": b.text} for b in row] for row in markup.keyboard],
        }
    return {"type": type(markup).__name__}


def message_view(msg) -> dict:
    """pyrogram Message -> 扁平 dict(AI 友好)。"""
    from_user = getattr(msg, "from_user", None)
    out = bool(getattr(msg, "out", False)) or bool(getattr(from_user, "is_self", False))
    return {
        "message_id": msg.id,
        "chat_id": msg.chat.id if getattr(msg, "chat", None) else None,
        "date": msg.date.isoformat() if getattr(msg, "date", None) else None,
        "edit_date": msg.edit_date.isoformat() if getattr(msg, "edit_date", None) else None,
        "out": out,
        "from": user_ref(from_user),
        "text": getattr(msg, "text", None) or getattr(msg, "caption", None),
        "media": str(msg.media.value) if getattr(msg, "media", None) else None,
        "reply_to_message_id": getattr(msg, "reply_to_message_id", None),
        "service": str(msg.service.value) if getattr(msg, "service", None) else None,
        "reply_markup": markup_view(getattr(msg, "reply_markup", None)),
    }
