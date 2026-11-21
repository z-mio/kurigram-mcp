"""论坛话题管理(领域聚合:覆盖 kurigram 2.2.27 全部 13 个论坛话题方法)。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import INTERNAL, McpError
from .views import forum_topic_view

if TYPE_CHECKING:
    from .client import TelegramClient

FORUM_ACTIONS = (
    "list",
    "get_by_id",
    "create",
    "edit",
    "close",
    "reopen",
    "delete",
    "pin",
    "unpin",
    "hide_general",
    "unhide_general",
    "unpin_all_messages",
    "toggle",
)


def _req(params: dict[str, Any], key: str, action: str) -> Any:
    val = params.get(key)
    if val is None or (isinstance(val, str) and not val.strip()):
        raise McpError(INTERNAL, f"action={action} 缺少必填参数: {key}")
    return val


async def manage_forum_topics(
    client: TelegramClient,
    chat_id: int,
    action: str,
    params: dict[str, Any] | None = None,
) -> dict:
    """论坛话题查询与管理(白名单校验由工具层完成)。"""
    p = params or {}
    act = action.strip().lower()
    raw = client.raw

    if act == "list":
        limit = int(p.get("limit", 50))
        topics = [forum_topic_view(t) async for t in raw.get_forum_topics(chat_id, limit=limit)]
        return {"chat_id": chat_id, "count": len(topics), "topics": topics}

    if act == "get_by_id":
        ids = _req(p, "topic_ids", act)
        topic_ids = [int(ids)] if isinstance(ids, (int, str)) else [int(x) for x in ids]
        res = await raw.get_forum_topics_by_id(chat_id, topic_ids)
        items = res if isinstance(res, list) else [res]
        topics = [forum_topic_view(t) for t in items if t is not None]
        return {"chat_id": chat_id, "count": len(topics), "topics": topics}

    if act == "create":
        name = str(_req(p, "name", act))
        icon_color = int(p["icon_color"]) if p.get("icon_color") is not None else None
        icon_emoji = str(p["icon_custom_emoji_id"]) if p.get("icon_custom_emoji_id") is not None else None
        topic = await raw.create_forum_topic(
            chat_id,
            name,
            icon_color=icon_color,
            icon_custom_emoji_id=icon_emoji,
        )
        return {"chat_id": chat_id, "topic": forum_topic_view(topic)}

    if act == "edit":
        tid = int(_req(p, "message_thread_id", act))
        ok = await raw.edit_forum_topic(
            chat_id,
            tid,
            name=str(p["name"]) if p.get("name") is not None else None,
            icon_custom_emoji_id=(
                str(p["icon_custom_emoji_id"]) if p.get("icon_custom_emoji_id") is not None else None
            ),
        )
        return {"chat_id": chat_id, "message_thread_id": tid, "ok": bool(ok)}

    if act == "close":
        tid = int(_req(p, "message_thread_id", act))
        ok = await raw.close_forum_topic(chat_id, tid)
        return {"chat_id": chat_id, "message_thread_id": tid, "ok": bool(ok)}

    if act == "reopen":
        tid = int(_req(p, "message_thread_id", act))
        # kurigram 2.2.27 源码把 message_thread_id 误标为 str,实际传 int 给 EditForumTopic(topic_id=...)
        ok = await raw.reopen_forum_topic(chat_id, tid)  # type: ignore[arg-type]
        return {"chat_id": chat_id, "message_thread_id": tid, "ok": bool(ok)}

    if act == "delete":
        tid = int(_req(p, "message_thread_id", act))
        ok = await raw.delete_forum_topic(chat_id, tid)
        return {"chat_id": chat_id, "message_thread_id": tid, "ok": bool(ok)}

    if act == "pin":
        tid = int(_req(p, "message_thread_id", act))
        ok = await raw.pin_forum_topic(chat_id, tid)
        return {"chat_id": chat_id, "message_thread_id": tid, "ok": bool(ok)}

    if act == "unpin":
        tid = int(_req(p, "message_thread_id", act))
        ok = await raw.unpin_forum_topic(chat_id, tid)
        return {"chat_id": chat_id, "message_thread_id": tid, "ok": bool(ok)}

    if act == "hide_general":
        ok = await raw.hide_general_forum_topic(chat_id)
        return {"chat_id": chat_id, "ok": bool(ok)}

    if act == "unhide_general":
        ok = await raw.unhide_general_forum_topic(chat_id)
        return {"chat_id": chat_id, "ok": bool(ok)}

    if act == "unpin_all_messages":
        tid = int(_req(p, "message_thread_id", act))
        ok = await raw.unpin_all_forum_topic_messages(chat_id, tid)
        return {"chat_id": chat_id, "message_thread_id": tid, "ok": bool(ok)}

    if act == "toggle":
        ok = await raw.toggle_forum_topics(
            chat_id,
            is_forum=bool(p.get("is_forum", True)),
            has_forum_tabs=bool(p.get("has_forum_tabs", False)),
            has_forum_sidebar=bool(p.get("has_forum_sidebar", False)),
        )
        return {"chat_id": chat_id, "ok": bool(ok)}

    raise McpError(INTERNAL, f"未知的 forum action: {action}(支持: {', '.join(FORUM_ACTIONS)})")
