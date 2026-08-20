"""Telegram 对象 -> 扁平 JSON 的序列化视图。"""

from __future__ import annotations

import re


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
    view = {f: getattr(chat, f, None) for f in fields}
    # kurigram 怪癖:bot 私聊 Chat 的 is_bot 不填充,只有 type=bot —— 显式补齐
    chat_type = getattr(view.get("type"), "value", view.get("type"))
    if view["is_bot"] is None and str(chat_type).lower() == "bot":
        view["is_bot"] = True
    # photo 展平:ChatPhoto 对象 JSON 序列化会变成带转义字符串
    photo = view.get("photo")
    if photo is not None and not isinstance(photo, (str, dict)):
        view["photo"] = {
            "photo_id": getattr(photo, "photo_id", None),
            "small_file_id": getattr(photo, "small_file_id", None),
            "big_file_id": getattr(photo, "big_file_id", None),
        }
    return view


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


def poll_view(poll) -> dict | None:
    """pyrogram Poll -> 扁平 dict(投票类工具返回)。"""
    if poll is None:
        return None
    options = []
    for o in (getattr(poll, "options", None) or []):
        # 新版属性名 voter_count;旧版 voters 兜底
        voters = getattr(o, "voter_count", None)
        if voters is None:
            voters = getattr(o, "voters", 0)
        options.append(
            {
                "text": getattr(o, "text", None),
                "voters": voters,
                "data": getattr(o, "data", None),
            }
        )
    return {
        "id": getattr(poll, "id", None),
        "question": getattr(poll, "question", None),
        "options": options,
        "total_voters": getattr(poll, "total_voters", None)
        or getattr(poll, "total_voter_count", None),
        "is_closed": bool(getattr(poll, "is_closed", False)),
        "is_anonymous": bool(getattr(poll, "is_anonymous", False)),
        "type": getattr(getattr(poll, "type", None), "value", None),
    }


def inline_result_view(result) -> dict:
    """raw BotInlineResult/BotInlineMediaResult -> 扁平 dict(内联查询结果)。"""
    out: dict = {
        "id": getattr(result, "id", None),
        "type": getattr(result, "type", None),
        "title": getattr(result, "title", None),
        "description": getattr(result, "description", None),
        "url": getattr(result, "url", None),
        "thumb_url": None,
        "message": None,
    }
    thumb = getattr(result, "thumb", None)
    if thumb is not None:
        out["thumb_url"] = getattr(thumb, "url", None)
    send_message = getattr(result, "send_message", None)
    if send_message is not None:
        out["message"] = getattr(send_message, "message", None)
    return out


def _iso(ts) -> str | None:
    """datetime -> ISO 字符串;naive UTC 补 Z 后缀,避免被误读为本地时间。"""
    if ts is None:
        return None
    iso = ts.isoformat()
    if ts.tzinfo is None:
        iso += "Z"
    return iso


def _entity_type_label(e) -> str | None:
    """实体类型 -> 简洁标签。

    真实形态:pyrogram 高层 MessageEntity.type 是 MessageEntityType 枚举,
    其 .value 是 raw 实体类,JSON 序列化会变成 "<class '...'>" 噪音字符串——
    统一规整为类名(如 MessageEntityBold)。SimpleNamespace/字符串原样返回。
    """
    raw = getattr(e, "type", None)
    raw = getattr(raw, "value", raw)  # 枚举 -> raw 类
    if isinstance(raw, type):
        return raw.__name__
    if isinstance(raw, str):
        m = re.search(r"\.([A-Za-z_]+)'>$", raw) if raw.startswith("<class") else None
        return m.group(1) if m else raw
    return None


def _links_of(msg) -> list[dict] | None:
    """从消息 entities/caption_entities 提取超链接(如文本 "WIKI" 实际指向 https://...)。

    Telegram 常用"文本+url 实体"表达链接,纯文本视图会丢失 URL——
    子会话实测发现 bot 回复 "Bot使用文档: WIKI" 实际是超链接。
    caption 消息的实体在 caption_entities 而非 entities。
    """
    entities = list(getattr(msg, "entities", None) or []) + list(
        getattr(msg, "caption_entities", None) or []
    )
    text = getattr(msg, "text", None) or getattr(msg, "caption", None)
    if not entities or not text:
        return None
    links = []
    for e in entities:
        url = getattr(e, "url", None)
        if not url:
            continue
        offset = getattr(e, "offset", None)
        length = getattr(e, "length", None)
        segment = None
        if isinstance(offset, int) and isinstance(length, int):
            segment = text[offset : offset + length]
        links.append({"text": segment, "url": url, "type": _entity_type_label(e)})
    return links or None


def _entities_of(msg) -> list[dict] | None:
    """消息实体摘要(类型+文本片段),不含 url 详情(见 links)。

    用途:验证格式是否生效——如非 Premium 账号发送 custom_emoji 实体会被
    Telegram 静默丢弃,读回后 entities 为空即可发现降级。
    """
    entities = list(getattr(msg, "entities", None) or []) + list(
        getattr(msg, "caption_entities", None) or []
    )
    text = getattr(msg, "text", None) or getattr(msg, "caption", None)
    if not entities or not text:
        return None
    out = []
    for e in entities:
        offset = getattr(e, "offset", None)
        length = getattr(e, "length", None)
        segment = None
        if isinstance(offset, int) and isinstance(length, int):
            segment = text[offset : offset + length]
        out.append({"type": _entity_type_label(e), "text": segment})
    return out or None


def message_view(msg) -> dict:
    """pyrogram Message -> 扁平 dict(AI 友好)。"""
    from_user = getattr(msg, "from_user", None)
    out = bool(getattr(msg, "out", False)) or bool(getattr(from_user, "is_self", False))
    return {
        "message_id": msg.id,
        "chat_id": msg.chat.id if getattr(msg, "chat", None) else None,
        "date": _iso(getattr(msg, "date", None)),
        "edit_date": _iso(getattr(msg, "edit_date", None)),
        "out": out,
        "is_outgoing": out,  # out 的语义别名,便于理解
        "from": user_ref(from_user),
        "text": getattr(msg, "text", None) or getattr(msg, "caption", None),
        "entities": _entities_of(msg),
        "links": _links_of(msg),
        "media": str(msg.media.value) if getattr(msg, "media", None) else None,
        "media_group_id": getattr(msg, "media_group_id", None),
        "poll": poll_view(getattr(msg, "poll", None)),
        "reply_to_message_id": getattr(msg, "reply_to_message_id", None),
        "service": str(msg.service.value) if getattr(msg, "service", None) else None,
        "reply_markup": markup_view(getattr(msg, "reply_markup", None)),
    }
