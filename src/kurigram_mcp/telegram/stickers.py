"""贴纸与贴纸包管理(领域聚合:覆盖 kurigram 2.2.27 全部 28 个用户可用贴纸方法)。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyrogram.enums import MaskPointType, StickerFormat, StickerType
from pyrogram.types import InputSticker, MaskPosition

from ..errors import INTERNAL, McpError
from ..files import resolve_media_ref
from .views import sticker_set_view, sticker_view

if TYPE_CHECKING:
    from .client import TelegramClient

QUERY_ACTIONS = (
    "get_set",
    "get_owned_sets",
    "get_custom_emoji",
    "search",
    "search_sets",
    "favorites",
    "recent",
    "suggest_name",
)

MANAGE_ACTIONS = (
    "install",
    "uninstall",
    "archive",
    "reorder_sets",
    "add_favorite",
    "remove_favorite",
    "add_recent",
    "remove_recent",
    "clear_recent",
    "create_set",
    "add_to_set",
    "replace_in_set",
    "delete_from_set",
    "delete_set",
    "set_title",
    "set_thumbnail",
    "set_custom_emoji_thumbnail",
    "set_emoji_list",
    "set_keywords",
    "set_mask_position",
    "set_position",
    "upload_file",
)


def _req(params: dict[str, Any], key: str, action: str) -> Any:
    val = params.get(key)
    if val is None or (isinstance(val, str) and not val.strip()):
        raise McpError(INTERNAL, f"action={action} 缺少必填参数: {key}")
    return val


def _sticker_type(val: Any) -> StickerType:
    key = str(val or "regular").strip().upper()
    try:
        return StickerType[key]
    except KeyError as exc:
        raise McpError(INTERNAL, f"不支持的 sticker_type: {val}(支持: regular/mask/custom_emoji)") from exc


def _sticker_format(val: Any) -> StickerFormat:
    key = str(val or "static").strip().upper()
    try:
        return StickerFormat[key]
    except KeyError as exc:
        raise McpError(INTERNAL, f"不支持的 sticker format: {val}(支持: static/animated/video)") from exc


def _mask_position(raw: Any) -> MaskPosition | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise McpError(INTERNAL, "mask_position 需为 dict: {point, x_shift, y_shift, scale}")
    pt_raw = str(raw.get("point") or "").strip().upper()
    try:
        point = MaskPointType[pt_raw]
    except KeyError as exc:
        raise McpError(INTERNAL, f"不支持的 mask point: {pt_raw}(支持: forehead/eyes/mouth/chin)") from exc
    return MaskPosition(
        point=point,
        x_shift=float(raw.get("x_shift", 0.0)),
        y_shift=float(raw.get("y_shift", 0.0)),
        scale=float(raw.get("scale", 1.0)),
    )


def _input_sticker(item: Any, uploads_dir: Any) -> InputSticker:
    if not isinstance(item, dict):
        raise McpError(INTERNAL, "InputSticker 条目需为 dict: {sticker, format, emoji_list, ...}")
    src = item.get("sticker")
    if not src:
        raise McpError(INTERNAL, "InputSticker 缺少 sticker(路径/file_id/URL/upload://)")
    src = resolve_media_ref(src, uploads_dir)
    emojis = item.get("emoji_list") or item.get("emojis")
    if isinstance(emojis, str):
        emojis = [emojis]
    if not isinstance(emojis, list) or not emojis:
        raise McpError(INTERNAL, "InputSticker 缺少 emoji_list(至少一个 emoji)")
    kw = item.get("keywords")
    return InputSticker(
        sticker=src,
        format=_sticker_format(item.get("format") or item.get("sticker_format") or "static"),
        emoji_list=[str(e) for e in emojis],
        mask_position=_mask_position(item.get("mask_position")),
        keywords=[str(k) for k in kw] if isinstance(kw, list) else None,
    )


def _user_id_or_self(client: TelegramClient, params: dict[str, Any]) -> int | str:
    uid = params.get("user_id")
    if uid is not None:
        return uid if isinstance(uid, (int, str)) else int(uid)
    return client.me.id


async def stickers_query(client: TelegramClient, action: str, params: dict[str, Any] | None = None) -> dict:
    """只读查询贴纸/贴纸包。"""
    p = params or {}
    act = action.strip().lower()
    raw = client.raw

    if act == "get_set":
        name = str(_req(p, "name", act))
        ss = await raw.get_sticker_set(name)
        return sticker_set_view(ss) or {}

    if act == "get_owned_sets":
        limit = int(p.get("limit", 20))
        offset = int(p.get("offset_sticker_set_id", 0))
        sets = [
            sticker_set_view(ss, include_stickers=False)
            async for ss in raw.get_owned_sticker_sets(limit=limit, offset_sticker_set_id=offset)
        ]
        return {"count": len(sets), "sets": sets}

    if act == "get_custom_emoji":
        ids = _req(p, "custom_emoji_ids", act)
        if isinstance(ids, (str, int)):
            ids = [str(ids)]
        stickers = await raw.get_custom_emoji_stickers([str(x) for x in ids])
        return {"count": len(stickers), "stickers": [sticker_view(s) for s in stickers]}

    if act == "search":
        st = _sticker_type(p.get("sticker_type", "regular"))
        emojis = p.get("emojis") or []
        if isinstance(emojis, str):
            emojis = [emojis]
        query = str(p.get("query") or "")
        langs = p.get("input_languages_codes")
        offset = int(p.get("offset", 0))
        limit = int(p.get("limit", 20))
        found = [
            sticker_view(s)
            async for s in raw.search_stickers(
                st,
                [str(e) for e in emojis],
                query=query,
                input_languages_codes=[str(x) for x in langs] if isinstance(langs, list) else None,
                offset=offset,
                limit=limit,
            )
        ]
        return {"count": len(found), "stickers": found}

    if act == "search_sets":
        st = _sticker_type(p.get("sticker_type", "regular"))
        query = str(_req(p, "query", act))
        found_sets = await raw.search_sticker_sets(st, query)
        return {"count": len(found_sets), "sets": [sticker_set_view(ss, include_stickers=False) for ss in found_sets]}

    if act == "favorites":
        stickers = await raw.get_favorite_stickers()
        return {"count": len(stickers), "stickers": [sticker_view(s) for s in stickers]}

    if act == "recent":
        is_attached = p.get("is_attached")
        stickers = await raw.get_recent_stickers(is_attached=is_attached)
        return {"count": len(stickers), "stickers": [sticker_view(s) for s in stickers]}

    if act == "suggest_name":
        title = str(_req(p, "title", act))
        suggested = await raw.get_suggested_sticker_set_name(title)
        return {"title": title, "name": suggested}

    raise McpError(INTERNAL, f"未知的 stickers_query action: {action}(支持: {', '.join(QUERY_ACTIONS)})")


async def stickers_manage(client: TelegramClient, action: str, params: dict[str, Any] | None = None) -> dict:
    """写操作:安装/卸载/收藏/最近贴纸/贴纸包增删改。"""
    p = params or {}
    act = action.strip().lower()
    raw = client.raw
    uploads_dir = client.settings.uploads_dir

    if act == "install":
        name = str(_req(p, "name", act))
        ok = await raw.change_sticker_set(name, is_installed=True, is_archived=False)
        return {"action": act, "name": name, "ok": bool(ok)}

    if act == "uninstall":
        name = str(_req(p, "name", act))
        ok = await raw.change_sticker_set(name, is_installed=False, is_archived=False)
        return {"action": act, "name": name, "ok": bool(ok)}

    if act == "archive":
        name = str(_req(p, "name", act))
        ok = await raw.change_sticker_set(name, is_installed=False, is_archived=True)
        return {"action": act, "name": name, "ok": bool(ok)}

    if act == "reorder_sets":
        st = _sticker_type(p.get("sticker_type", "regular"))
        ids = _req(p, "sticker_set_ids", act)
        ok = await raw.reorder_installed_sticker_sets(st, [int(x) for x in ids])
        return {"action": act, "ok": bool(ok)}

    if act == "add_favorite":
        sticker = str(_req(p, "sticker", act))
        ok = await raw.add_favorite_sticker(sticker)
        return {"action": act, "ok": bool(ok)}

    if act == "remove_favorite":
        sticker = str(_req(p, "sticker", act))
        ok = await raw.remove_favorite_sticker(sticker)
        return {"action": act, "ok": bool(ok)}

    if act == "add_recent":
        sticker = str(_req(p, "sticker", act))
        ok = await raw.add_recent_sticker(sticker, is_attached=p.get("is_attached"))
        return {"action": act, "ok": bool(ok)}

    if act == "remove_recent":
        sticker = str(_req(p, "sticker", act))
        ok = await raw.remove_recent_sticker(sticker, is_attached=p.get("is_attached"))
        return {"action": act, "ok": bool(ok)}

    if act == "clear_recent":
        ok = await raw.clear_recent_stickers(is_attached=p.get("is_attached"))
        return {"action": act, "ok": bool(ok)}

    if act == "create_set":
        name = str(_req(p, "name", act))
        title = str(_req(p, "title", act))
        raw_stickers = _req(p, "stickers", act)
        if not isinstance(raw_stickers, list) or not raw_stickers:
            raise McpError(INTERNAL, "create_set 的 stickers 需为非空列表")
        items = [_input_sticker(it, uploads_dir) for it in raw_stickers]
        ss = await raw.create_new_sticker_set(
            user_id=_user_id_or_self(client, p),
            name=name,
            title=title,
            stickers=items,
            sticker_type=_sticker_type(p.get("sticker_type", "regular")),
            needs_repainting=p.get("needs_repainting"),
        )
        return sticker_set_view(ss) or {}

    if act == "add_to_set":
        name = str(_req(p, "name", act))
        item = _input_sticker(_req(p, "sticker", act), uploads_dir)
        ss = await raw.add_sticker_to_set(user_id=_user_id_or_self(client, p), name=name, sticker=item)
        return sticker_set_view(ss) or {}

    if act == "replace_in_set":
        old = str(_req(p, "old_sticker", act))
        item = _input_sticker(_req(p, "sticker", act), uploads_dir)
        ss = await raw.replace_sticker_in_set(user_id=_user_id_or_self(client, p), old_sticker=old, sticker=item)
        return sticker_set_view(ss) or {}

    if act == "delete_from_set":
        sticker = str(_req(p, "sticker", act))
        ss = await raw.delete_sticker_from_set(sticker)
        return sticker_set_view(ss) or {}

    if act == "delete_set":
        name = str(_req(p, "name", act))
        ok = await raw.delete_sticker_set(name)
        return {"action": act, "name": name, "ok": bool(ok)}

    if act == "set_title":
        name = str(_req(p, "name", act))
        title = str(_req(p, "title", act))
        ss = await raw.set_sticker_set_title(name, title)
        return sticker_set_view(ss) or {}

    if act == "set_thumbnail":
        name = str(_req(p, "name", act))
        fmt = _sticker_format(p.get("format") or p.get("sticker_format") or "static")
        thumb = p.get("thumbnail")
        if thumb is not None:
            thumb = resolve_media_ref(thumb, uploads_dir)
        ss = await raw.set_sticker_set_thumbnail(
            user_id=_user_id_or_self(client, p),
            name=name,
            format=fmt,
            thumbnail=thumb,
        )
        return sticker_set_view(ss) or {}

    if act == "set_custom_emoji_thumbnail":
        name = str(_req(p, "name", act))
        cid = str(p.get("custom_emoji_id") or "")
        ss = await raw.set_custom_emoji_sticker_set_thumbnail(name, custom_emoji_id=cid)
        return sticker_set_view(ss) or {}

    if act == "set_emoji_list":
        sticker = str(_req(p, "sticker", act))
        emojis = _req(p, "emoji_list", act)
        if isinstance(emojis, str):
            emojis = [emojis]
        ss = await raw.set_sticker_emoji_list(sticker, [str(e) for e in emojis])
        return sticker_set_view(ss) or {}

    if act == "set_keywords":
        sticker = str(_req(p, "sticker", act))
        kw = p.get("keywords")
        ss = await raw.set_sticker_keywords(sticker, [str(k) for k in kw] if isinstance(kw, list) else None)
        return sticker_set_view(ss) or {}

    if act == "set_mask_position":
        sticker = str(_req(p, "sticker", act))
        ss = await raw.set_sticker_mask_position(sticker, _mask_position(p.get("mask_position")))
        return sticker_set_view(ss) or {}

    if act == "set_position":
        sticker = str(_req(p, "sticker", act))
        pos = int(_req(p, "position", act))
        ss = await raw.set_sticker_position_in_set(sticker, pos)
        return sticker_set_view(ss) or {}

    if act == "upload_file":
        src = resolve_media_ref(_req(p, "sticker", act), uploads_dir)
        fmt = _sticker_format(p.get("sticker_format") or p.get("format") or "static")
        f = await raw.upload_sticker_file(
            user_id=_user_id_or_self(client, p),
            sticker=src,
            sticker_format=fmt,
        )
        return {
            "file_id": getattr(f, "file_id", None),
            "file_unique_id": getattr(f, "file_unique_id", None),
            "file_size": getattr(f, "file_size", None),
        }

    raise McpError(INTERNAL, f"未知的 stickers_manage action: {action}(支持: {', '.join(MANAGE_ACTIONS)})")
