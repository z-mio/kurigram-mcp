"""Telegram 对象 -> 扁平 JSON 的序列化视图。

本模块刻意采用鸭子类型:入参既可能是 pyrogram 高层对象(User/Chat/Message/Poll…),
也可能是 raw 对象或测试里的 SimpleNamespace 替身。统一标注为 Any,
避免把"缺字段也不报错"的容错语义钉死在某一个具体类型上。
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any


def _verification_view(obj: Any) -> dict:
    """verification_status -> 扁平 dict。

    kurigram 2.2.25+ 将 User/Chat 的 is_verified/is_scam/is_fake 标记为弃用,
    迁移到 obj.verification_status.*;此处直接读新接口,输出键保持不变。
    """
    vs = getattr(obj, "verification_status", None) or None
    if vs is None:
        return {"is_verified": None, "is_scam": None, "is_fake": None}
    return {
        "is_verified": getattr(vs, "is_verified", None),
        "is_scam": getattr(vs, "is_scam", None),
        "is_fake": getattr(vs, "is_fake", None),
    }


def user_view(user: Any) -> dict:
    """pyrogram User -> 扁平 dict(缺字段容错)。"""
    fields = (
        "id",
        "is_bot",
        "is_restricted",
        "first_name",
        "last_name",
        "username",
        "language_code",
        "dc_id",
    )
    view = {f: getattr(user, f, None) for f in fields}
    view.update(_verification_view(user))
    return view


def chat_view(chat: Any) -> dict:
    """pyrogram Chat -> 扁平 dict。"""
    fields = (
        "id",
        "type",
        "title",
        "username",
        "first_name",
        "last_name",
        "is_bot",
        "is_restricted",
        "description",
        "members_count",
        "photo",
    )
    view = {f: getattr(chat, f, None) for f in fields}
    view.update(_verification_view(chat))
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


def user_ref(user: Any) -> dict | None:
    """消息中的发送者摘要。"""
    if user is None:
        return None
    return {
        "id": getattr(user, "id", None),
        "username": getattr(user, "username", None),
        "first_name": getattr(user, "first_name", None),
        "is_bot": bool(getattr(user, "is_bot", False)),
    }


def _button_view(btn: Any) -> dict:
    """InlineKeyboardButton -> 扁平 dict。"""
    out: dict = {"text": btn.text}
    cb = getattr(btn, "callback_data", None)
    if cb is not None:
        out["callback_data"] = cb.decode("utf-8", errors="replace") if isinstance(cb, bytes) else str(cb)
    if getattr(btn, "url", None):
        out["url"] = btn.url
    web_app = getattr(btn, "web_app", None)
    if web_app is not None:
        out["web_app"] = getattr(web_app, "url", None)
    if getattr(btn, "user_id", None):
        out["user_id"] = btn.user_id
    if getattr(btn, "switch_inline_query", None) is not None:
        out["switch_inline_query"] = btn.switch_inline_query
    if getattr(btn, "switch_inline_query_current_chat", None) is not None:
        out["switch_inline_query_current_chat"] = btn.switch_inline_query_current_chat
    login_url = getattr(btn, "login_url", None)
    if login_url is not None:
        out["login_url"] = getattr(login_url, "url", None)
    copy_text = getattr(btn, "copy_text", None)
    if copy_text is not None:
        out["copy_text"] = getattr(copy_text, "text", None)
    if getattr(btn, "requires_password", None):
        out["requires_password"] = True
    if getattr(btn, "callback_game", None) is not None:
        out["game"] = True
    if getattr(btn, "disabled", None) is not None:
        out["disabled"] = True
    if getattr(btn, "pay", False):
        out["pay"] = True
    style = getattr(btn, "style", None)
    # ButtonStyle 枚举取 name;SimpleNamespace/字符串替身 getattr 兜底
    style_name = getattr(style, "name", style if isinstance(style, str) else None)
    if style_name is not None and str(style_name).lower() != "default":
        out["style"] = str(style_name).lower()
    return out


def markup_view(markup: Any) -> dict | None:
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
        # kurigram 的 keyboard 允许纯字符串按钮(str | KeyboardButton)
        return {
            "type": "reply",
            "rows": [[{"text": b if isinstance(b, str) else b.text} for b in row] for row in markup.keyboard],
        }
    return {"type": type(markup).__name__}


def poll_view(poll: Any) -> dict | None:
    """pyrogram Poll -> 扁平 dict(投票类工具返回)。"""
    if poll is None:
        return None
    options = []
    for o in getattr(poll, "options", None) or []:
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
        "total_voters": getattr(poll, "total_voters", None) or getattr(poll, "total_voter_count", None),
        "is_closed": bool(getattr(poll, "is_closed", False)),
        "is_anonymous": bool(getattr(poll, "is_anonymous", False)),
        "type": getattr(getattr(poll, "type", None), "value", None),
    }


def inline_result_view(result: Any) -> dict:
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


def _iso(ts: datetime | None) -> str | None:
    """datetime -> ISO 字符串;naive UTC 补 Z 后缀,避免被误读为本地时间。"""
    if ts is None:
        return None
    iso = ts.isoformat()
    if ts.tzinfo is None:
        iso += "Z"
    return iso


def _rich_text(node: Any) -> str:
    """raw RichText -> 纯文本(递归)。

    Telegram 富消息(layer 228 rich_message)的内容以 RichText 树表达:
    TextPlain / TextConcat / TextItalic / TextBold / TextUrl 等;
    按结构递归展开(不依赖具体类名),链接/邮箱/用户附注原文。
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    # 内嵌按钮(TextButton 是 RichText 联合成员):渲染为 [label],
    # 按钮本体由 _text_buttons 收集进 rich.buttons
    if type(node).__name__ == "TextButton":
        return f"[{_rich_text(getattr(node, 'text', None))}]"
    url = getattr(node, "url", None)
    email = getattr(node, "email", None)
    user_id = getattr(node, "user_id", None)
    texts = getattr(node, "texts", None)
    text = getattr(node, "text", None)

    if url or email or user_id:
        inner = _rich_text(text) if text is not None else ""
        if url:
            url = html.unescape(url)
            return f"{inner} ({url})" if inner and url not in inner else inner or url
        if email:
            return f"{inner} ({email})" if inner else email
        return f"{inner} (user {user_id})" if inner else f"(user {user_id})"
    if texts:
        return "".join(_rich_text(t) for t in texts)
    if isinstance(text, str):
        return text
    if text is not None:
        return _rich_text(text)
    name = type(node).__name__
    if name == "TextImage":
        return "[图片]"
    if name == "TextCustomEmoji":
        # 自定义表情:alt 是兜底字符(通常就是 emoji 本体)
        return getattr(node, "alt", None) or "[emoji]"
    if name == "TextMath":
        return getattr(node, "source", None) or ""
    return ""


def _caption(c: Any) -> str:
    """caption -> 纯文本。PageCaption(text+credit) 附注来源;裸 RichText 直接渲染。"""
    if c is None:
        return ""
    if hasattr(c, "credit"):
        text = _rich_text(getattr(c, "text", None))
        credit = _rich_text(getattr(c, "credit", None))
        return f"{text} — {credit}" if credit else text
    return _rich_text(c)


def _views_of(blocks: Any, rich: Any) -> list[dict]:
    """渲染一组 PageBlock,丢弃完全提取不出内容的项。"""
    return [v for v in (_block_view(x, rich) for x in blocks or []) if v is not None]


def _views_text(views: list[dict]) -> str:
    """已渲染 block 的 text 拼接(跳过空串)。"""
    return "\n".join(v["text"] for v in views if v.get("text"))


def _list_block_view(b: Any, ordered: bool, rich: Any) -> dict:
    """PageBlockList / PageBlockOrderedList -> dict。

    条目分两种:PageListItem*Text(纯文本)与 PageListItem*Blocks(嵌套 block,
    guest bot 列表实际走这种,只读 .text 会得到空串——曾经的丢内容点)。
    """
    items = []
    lines = []
    for i, it in enumerate(getattr(b, "items", None) or []):
        checkbox = bool(getattr(it, "checkbox", False))
        checked = bool(getattr(it, "checked", False))
        if ordered:
            num = getattr(it, "num", None)
            value = getattr(it, "value", None)
            label = num or (f"{value}." if value else f"{i + 1}.")
        else:
            label = "•"
        item: dict = {"label": label}
        inner = getattr(it, "blocks", None)
        if inner is not None:
            views = _views_of(inner, rich)
            item["blocks"] = views
            text = _views_text(views)
        else:
            text = _rich_text(getattr(it, "text", None))
        item["text"] = text
        if checkbox:
            item["checked"] = checked
        items.append(item)
        if text:
            marker = "[x] " if checked else "[ ] " if checkbox else ""
            lines.append(f"{label} {marker}{text}")
    return {"type": "orderedlist" if ordered else "list", "items": items, "text": "\n".join(lines)}


def _block_view(b: Any, rich: Any) -> dict | None:
    """单个 PageBlock -> dict(递归容器);b 为 None 时返回 None。

    按 raw 类名分发:文本块 / 容器块 / 媒体块 / 按钮行……
    未知类型走兜底(有 text 渲染 text,有 blocks/items 递归),不静默丢弃;
    什么都提取不出来才标 unsupported。
    """
    if b is None:
        return None
    name = type(b).__name__
    btype = name.removeprefix("PageBlock").lower() if name.startswith("PageBlock") else "block"

    if name == "PageBlockDivider":
        return {"type": "divider", "text": "---"}
    if name == "PageBlockMath":
        return {"type": "math", "text": getattr(b, "source", None) or ""}
    if name == "PageBlockAnchor":
        return {"type": "anchor", "name": getattr(b, "name", None), "text": ""}
    if name == "PageBlockPreformatted":
        return {
            "type": "preformatted",
            "text": _rich_text(getattr(b, "text", None)),
            "language": getattr(b, "language", None),
        }
    if name == "PageBlockDetails":
        title = _rich_text(getattr(b, "title", None))
        views = _views_of(getattr(b, "blocks", None), rich)
        return {
            "type": "details",
            "title": title,
            "open": bool(getattr(b, "open", False)),
            "blocks": views,
            "text": "\n".join(x for x in (title, _views_text(views)) if x),
        }
    if name in ("PageBlockBlockquote", "PageBlockPullquote"):
        out: dict = {
            "type": btype,
            "text": _rich_text(getattr(b, "text", None)),
            "credit": _rich_text(getattr(b, "caption", None)) or None,
        }
        if name == "PageBlockBlockquote":
            out["collapsed"] = bool(getattr(b, "collapsed", False))
        return out
    if name == "PageBlockBlockquoteBlocks":
        views = _views_of(getattr(b, "blocks", None), rich)
        return {
            "type": "blockquoteblocks",
            "blocks": views,
            "credit": _rich_text(getattr(b, "caption", None)) or None,
            "text": _views_text(views),
        }
    if name in ("PageBlockList", "PageBlockOrderedList"):
        return _list_block_view(b, name == "PageBlockOrderedList", rich)
    if name == "PageBlockPhoto":
        cap = _caption(getattr(b, "caption", None))
        photo_id = getattr(b, "photo_id", None)
        out = {
            "type": "photo",
            # 64 位 id 转字符串,避免 JS 端 JSON 丢精度
            "photo_id": str(photo_id) if photo_id is not None else None,
            "spoiler": bool(getattr(b, "spoiler", False)),
            "caption": cap or None,
            "text": "[图片]" + (f" {cap}" if cap else ""),
        }
        if getattr(b, "url", None):
            out["url"] = b.url
        return out
    if name in ("PageBlockVideo", "PageBlockAudio", "PageBlockDocument"):
        field, label = {
            "PageBlockVideo": ("video_id", "[视频]"),
            "PageBlockAudio": ("audio_id", "[音频]"),
            "PageBlockDocument": ("document_id", "[文件]"),
        }[name]
        doc_id = getattr(b, field, None)
        out = {"type": btype, "document_id": str(doc_id) if doc_id is not None else None}
        file_name = None
        # rich.documents 里按 id 找回 mime/file_name(block 只带引用)
        doc = next((d for d in getattr(rich, "documents", None) or [] if getattr(d, "id", None) == doc_id), None)
        if doc is not None:
            out["mime_type"] = getattr(doc, "mime_type", None)
            file_name = next(
                (
                    a.file_name
                    for a in getattr(doc, "attributes", None) or []
                    if type(a).__name__ == "DocumentAttributeFilename"
                ),
                None,
            )
            if file_name:
                out["file_name"] = file_name
        cap = _caption(getattr(b, "caption", None))
        out["caption"] = cap or None
        out["text"] = " ".join(x for x in (label, file_name, cap) if x)
        return out
    if name in ("PageBlockCollage", "PageBlockSlideshow"):
        views = _views_of(getattr(b, "items", None), rich)
        cap = _caption(getattr(b, "caption", None))
        return {
            "type": btype,
            "blocks": views,
            "caption": cap or None,
            "text": "\n".join(x for x in (_views_text(views), cap) if x),
        }
    if name == "PageBlockTable":
        title = _rich_text(getattr(b, "title", None))
        rows = [
            [_rich_text(getattr(c, "text", None)) for c in getattr(row, "cells", None) or []]
            for row in getattr(b, "rows", None) or []
        ]
        lines = ([title] if title else []) + [" | ".join(r) for r in rows]
        return {"type": "table", "title": title or None, "rows": rows, "text": "\n".join(lines)}
    if name == "PageBlockMap":
        geo = getattr(b, "geo", None)
        is_point = type(geo).__name__ == "GeoPoint"
        lat = getattr(geo, "lat", None) if is_point else None
        long = getattr(geo, "long", None) if is_point else None
        return {
            "type": "map",
            "lat": lat,
            "long": long,
            "zoom": getattr(b, "zoom", None),
            "caption": _caption(getattr(b, "caption", None)) or None,
            "text": f"[地图 {lat},{long}]" if is_point else "[地图]",
        }
    if name == "PageBlockEmbed":
        url = getattr(b, "url", None)
        return {
            "type": "embed",
            "url": url,
            "caption": _caption(getattr(b, "caption", None)) or None,
            "text": f"[嵌入] {url}" if url else "[嵌入]",
        }
    if name == "PageBlockEmbedPost":
        views = _views_of(getattr(b, "blocks", None), rich)
        author = getattr(b, "author", None)
        return {
            "type": "embedpost",
            "url": getattr(b, "url", None),
            "author": author,
            "blocks": views,
            "text": "\n".join(x for x in (author, _views_text(views)) if x),
        }
    if name == "PageBlockCover":
        views = _views_of([getattr(b, "cover", None)], rich)
        return {"type": "cover", "blocks": views, "text": _views_text(views)}
    if name == "PageBlockAuthorDate":
        return {
            "type": "authordate",
            "author": _rich_text(getattr(b, "author", None)) or None,
            "published_date": getattr(b, "published_date", None),
            "text": _rich_text(getattr(b, "author", None)),
        }
    if name == "PageBlockRelatedArticles":
        title = _rich_text(getattr(b, "title", None))
        articles = [
            {"title": getattr(a, "title", None), "url": getattr(a, "url", None)}
            for a in getattr(b, "articles", None) or []
        ]
        lines = [" ".join(x for x in (a["title"], a["url"]) if x) for a in articles]
        return {
            "type": "relatedarticles",
            "title": title or None,
            "articles": articles,
            "text": "\n".join(x for x in [title, *lines] if x),
        }
    if name == "PageBlockChannel":
        return {"type": "channel", "text": ""}
    if name == "PageBlockButtonRow":
        buttons = [_page_button_view(pb) for pb in getattr(b, "buttons", None) or []]
        align = None
        for flag, val in (("align_left", "left"), ("align_center", "center"), ("align_right", "right")):
            if getattr(b, flag, None):
                align = val
                break
        return {
            "type": "buttonrow",
            "buttons": buttons,
            "align": align,
            "text": " ".join(f"[{x['text']}]" for x in buttons),
        }

    # 兜底:RichText text / 嵌套 blocks / items,能提什么提什么
    text_node = getattr(b, "text", None)
    if text_node is not None:
        out = {"type": btype, "text": _rich_text(text_node)}
    else:
        views = _views_of(getattr(b, "blocks", None) or getattr(b, "items", None), rich)
        if views:
            out = {"type": btype, "blocks": views, "text": _views_text(views)}
        else:
            out = {"type": btype, "text": "", "unsupported": True}
    cap = _caption(getattr(b, "caption", None))
    if cap:
        out["caption"] = cap
    return out


def _page_button_view(pb: Any) -> dict:
    """raw PageButton -> 扁平 dict(富消息按钮)。"""
    out: dict = {"text": _rich_text(getattr(pb, "text", None))}
    bt = getattr(pb, "type", None)
    kind = type(bt).__name__.removeprefix("InlineButtonType").lower() if bt is not None else "unknown"
    out["type"] = kind
    if kind == "callback":
        data = getattr(bt, "data", None)
        out["callback_data"] = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data or "")
        if getattr(bt, "requires_password", None):
            out["requires_password"] = True
    elif kind in ("url", "urlauth", "webview"):
        out["url"] = getattr(bt, "url", None)
    elif kind == "copy":
        out["copy_text"] = getattr(bt, "copy_text", None)
    elif kind == "userprofile":
        out["user_id"] = getattr(bt, "user_id", None)
    elif kind == "switchinline":
        out["switch_inline_query"] = getattr(bt, "query", None)
        out["same_peer"] = bool(getattr(bt, "same_peer", False))
    style = getattr(pb, "style", None)
    if style is not None:
        # RichButtonStyle:bg_* 是 flags 位,取第一个为真的
        for key, label in (
            ("bg_primary", "primary"),
            ("bg_danger", "danger"),
            ("bg_success", "success"),
            ("link", "link"),
        ):
            if getattr(style, key, None):
                out["style"] = label
                break
    return out


def _text_buttons(node: Any) -> list[Any]:
    """DFS 收集 RichText 树里的 TextButton 节点(文档顺序)。

    TextButton 是 RichText 联合成员(bot 面板常把它嵌在表格单元格 /
    段落里);label 内部不再找按钮。
    """
    if node is None or isinstance(node, str):
        return []
    if type(node).__name__ == "TextButton":
        return [node]
    out: list[Any] = []
    texts = getattr(node, "texts", None)
    if isinstance(texts, list):
        for t in texts:
            out.extend(_text_buttons(t))
    text = getattr(node, "text", None)
    if text is not None and not isinstance(text, str):
        out.extend(_text_buttons(text))
    return out


def _caption_nodes(c: Any) -> list[Any]:
    """caption 属性 -> RichText 节点列表(PageCaption 拆 text+credit)。"""
    if c is None:
        return []
    if hasattr(c, "credit"):
        return [n for n in (getattr(c, "text", None), getattr(c, "credit", None)) if n is not None]
    return [c]


def _walk_buttons(raw_msg: Any) -> list[list[tuple[Any, str]]]:
    """raw Message -> [[(按钮, 位置)]],文档顺序(单一 DFS)。

    按钮来源有两类:PageBlockButtonRow 的 PageButton,以及内嵌在
    RichText 里的 TextButton(表格单元格 / 列表项 / 段落 / 标题等)。
    位置标签:buttonrow / table{k}[r][c] / list[i] / 块类型名
    (k 为 DFS 顺序的全局表格编号)。
    """
    rich = getattr(raw_msg, "rich_message", None)
    if rich is None:
        return []
    rows: list[list[tuple[Any, str]]] = []
    table_i = 0  # 遇到的第 k 个 PageBlockTable(含嵌套),DFS 顺序编号

    def add_text_row(nodes: list[Any], where: str) -> None:
        btns: list[Any] = []
        for node in nodes:
            btns.extend(_text_buttons(node))
        if btns:
            rows.append([(b, where) for b in btns])

    def walk(blocks: Any) -> None:
        for b in blocks or []:
            walk_block(b)

    def walk_block(b: Any) -> None:
        name = type(b).__name__
        if name == "PageBlockButtonRow":
            rows.append([(pb, "buttonrow") for pb in getattr(b, "buttons", None) or []])
            return
        if name == "PageBlockTable":
            # 表格:title 一行,然后每个含按钮的行一行(单元格左->右)
            nonlocal table_i
            k = table_i
            table_i += 1
            title = getattr(b, "title", None)
            if title is not None:
                add_text_row([title], f"table{k}[title]")
            for r, row in enumerate(getattr(b, "rows", None) or []):
                btns: list[tuple[Any, str]] = []
                for c, cell in enumerate(getattr(row, "cells", None) or []):
                    for tb in _text_buttons(getattr(cell, "text", None)):
                        btns.append((tb, f"table{k}[{r}][{c}]"))
                if btns:
                    rows.append(btns)
            return
        if name in ("PageBlockList", "PageBlockOrderedList"):
            for i, it in enumerate(getattr(b, "items", None) or []):
                inner = getattr(it, "blocks", None)
                if inner is not None:
                    walk(inner)
                else:
                    add_text_row([getattr(it, "text", None)], f"list[{i}]")
            return
        # 其他块:自身 RichText 属性(title -> text -> caption -> author)里的按钮
        nodes = [getattr(b, "title", None), getattr(b, "text", None)]
        nodes += _caption_nodes(getattr(b, "caption", None))
        nodes.append(getattr(b, "author", None))
        add_text_row(nodes, name.removeprefix("PageBlock").lower())
        cover = getattr(b, "cover", None)
        if cover is not None:
            walk_block(cover)
        for attr in ("blocks", "items"):
            children = getattr(b, attr, None)
            if isinstance(children, list):
                walk(children)

    walk(getattr(rich, "blocks", None))
    return rows


def rich_button_rows(raw_msg: Any) -> list[list[Any]]:
    """raw Message -> 富消息按钮行(raw PageButton/TextButton,文档顺序)。

    与 _block_view 同一套 DFS 遍历:PageBlockButtonRow 可嵌在 details /
    blockquoteblocks / 列表项 / collage / embedpost / cover 等容器里,
    TextButton 可内嵌在表格单元格 / 段落 / 列表项的 RichText 里。
    """
    return [[pb for pb, _where in row] for row in _walk_buttons(raw_msg)]


def _rich_message_view(raw_msg: Any) -> dict | None:
    """raw Message.rich_message -> 简化结构 {text, blocks, buttons, partial}。

    guest bot(AI 回复,如 @mira)的内容以富消息下发:普通 text 为空,
    实际内容在 rich_message.blocks(PageBlockParagraph 等)里。
    返回 None 表示该消息没有富内容。
    """
    rich = getattr(raw_msg, "rich_message", None)
    if rich is None:
        return None
    blocks = _views_of(getattr(rich, "blocks", None), rich)
    if not blocks:
        return None
    text = _views_text(blocks)
    # "in" 标注按钮所在位置(table{k}[r][c] / list[i] / buttonrow / 块类型)
    buttons = [[{**_page_button_view(pb), "in": where} for pb, where in row] for row in _walk_buttons(raw_msg)]
    return {
        "text": text or None,
        "blocks": blocks,
        "buttons": buttons or None,
        "partial": bool(getattr(rich, "part", False)),
    }


def _entity_type_label(e: Any) -> str | None:
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


def _links_of(msg: Any) -> list[dict] | None:
    """从消息 entities/caption_entities 提取超链接(如文本 "WIKI" 实际指向 https://...)。

    Telegram 常用"文本+url 实体"表达链接,纯文本视图会丢失 URL——
    子会话实测发现 bot 回复 "Bot使用文档: WIKI" 实际是超链接。
    caption 消息的实体在 caption_entities 而非 entities。
    """
    entities = list(getattr(msg, "entities", None) or []) + list(getattr(msg, "caption_entities", None) or [])
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


def _entities_of(msg: Any) -> list[dict] | None:
    """消息实体摘要(类型+文本片段),不含 url 详情(见 links)。

    用途:验证格式是否生效——如非 Premium 账号发送 custom_emoji 实体会被
    Telegram 静默丢弃,读回后 entities 为空即可发现降级。
    """
    entities = list(getattr(msg, "entities", None) or []) + list(getattr(msg, "caption_entities", None) or [])
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


def message_view(msg: Any) -> dict:
    """pyrogram Message -> 扁平 dict(AI 友好)。"""
    from_user = getattr(msg, "from_user", None)
    out = bool(getattr(msg, "out", False)) or bool(getattr(from_user, "is_self", False))
    raw_msg = getattr(msg, "raw", None)
    return {
        "message_id": msg.id,
        # 临时消息(ephemeral)id=0,真实 id 在 ephemeral_message_id
        "ephemeral_message_id": getattr(msg, "ephemeral_message_id", None),
        "chat_id": msg.chat.id if getattr(msg, "chat", None) else None,
        "date": _iso(getattr(msg, "date", None)),
        "edit_date": _iso(getattr(msg, "edit_date", None)),
        "out": out,
        "is_outgoing": out,  # out 的语义别名,便于理解
        "from": user_ref(from_user),
        "text": getattr(msg, "text", None) or getattr(msg, "caption", None),
        "caption": getattr(msg, "caption", None),  # 媒体消息的说明文字(text 同时回显)
        "rich": _rich_message_view(raw_msg),  # 富消息内容(guest bot AI 回复等)
        "entities": _entities_of(msg),
        "links": _links_of(msg),
        "media": str(msg.media.value) if getattr(msg, "media", None) else None,
        "media_group_id": getattr(msg, "media_group_id", None),
        "poll": poll_view(getattr(msg, "poll", None)),
        "reply_to_message_id": getattr(msg, "reply_to_message_id", None),
        "service": str(msg.service.value) if getattr(msg, "service", None) else None,
        "reply_markup": markup_view(getattr(msg, "reply_markup", None)),
    }
