"""扩展消息发送与消息操作(领域聚合:视频/动图/音频/位置/联系人/骰子/清单/置顶)。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyrogram.types import InputChecklist, InputChecklistTask

from ..errors import INTERNAL, McpError
from ..files import resolve_media_ref
from .client import _parse_mode, _reply
from .views import message_view

if TYPE_CHECKING:
    from .client import TelegramClient

EXTRA_SEND_KINDS = ("video", "animation", "audio", "location", "contact", "dice", "checklist")
EXTRA_MSG_ACTIONS = ("pin", "unpin", "mark_checklist")


def _req(params: dict[str, Any], key: str, ctx: str) -> Any:
    val = params.get(key)
    if val is None or (isinstance(val, str) and not val.strip()):
        raise McpError(INTERNAL, f"{ctx} 缺少必填参数: {key}")
    return val


async def send_extra(
    client: TelegramClient,
    chat_id: int,
    kind: str,
    params: dict[str, Any] | None = None,
    reply_to_message_id: int | None = None,
    message_thread_id: int | None = None,
) -> dict:
    """发送扩展类型消息(video/animation/audio/location/contact/dice/checklist)。"""
    p = params or {}
    k = kind.strip().lower()
    raw = client.raw
    uploads_dir = client.settings.uploads_dir
    reply = _reply(reply_to_message_id)

    if k == "video":
        media = resolve_media_ref(_req(p, "media", f"kind={k}"), uploads_dir)
        msg = await raw.send_video(
            chat_id,
            media,
            caption=str(p.get("caption") or ""),
            parse_mode=_parse_mode(p.get("parse_mode", "none")),
            has_spoiler=p.get("has_spoiler"),
            duration=int(p.get("duration", 0)),
            width=int(p.get("width", 0)),
            height=int(p.get("height", 0)),
            supports_streaming=bool(p.get("supports_streaming", True)),
            reply_parameters=reply,
            message_thread_id=message_thread_id,
        )
    elif k == "animation":
        media = resolve_media_ref(_req(p, "media", f"kind={k}"), uploads_dir)
        msg = await raw.send_animation(
            chat_id,
            media,
            caption=str(p.get("caption") or ""),
            parse_mode=_parse_mode(p.get("parse_mode", "none")),
            has_spoiler=p.get("has_spoiler"),
            duration=int(p.get("duration", 0)),
            width=int(p.get("width", 0)),
            height=int(p.get("height", 0)),
            reply_parameters=reply,
            message_thread_id=message_thread_id,
        )
    elif k == "audio":
        media = resolve_media_ref(_req(p, "media", f"kind={k}"), uploads_dir)
        msg = await raw.send_audio(
            chat_id,
            media,
            caption=str(p.get("caption") or ""),
            parse_mode=_parse_mode(p.get("parse_mode", "none")),
            duration=int(p.get("duration", 0)),
            performer=p.get("performer"),
            title=p.get("title"),
            reply_parameters=reply,
            message_thread_id=message_thread_id,
        )
    elif k == "location":
        lat = float(_req(p, "latitude", f"kind={k}"))
        lon = float(_req(p, "longitude", f"kind={k}"))
        msg = await raw.send_location(
            chat_id,
            lat,
            lon,
            horizontal_accuracy=float(p["horizontal_accuracy"]) if p.get("horizontal_accuracy") is not None else None,
            live_period=int(p["live_period"]) if p.get("live_period") is not None else None,
            heading=int(p["heading"]) if p.get("heading") is not None else None,
            proximity_alert_radius=(
                int(p["proximity_alert_radius"]) if p.get("proximity_alert_radius") is not None else None
            ),
            reply_parameters=reply,
            message_thread_id=message_thread_id,
        )
    elif k == "contact":
        phone = str(_req(p, "phone_number", f"kind={k}"))
        first_name = str(_req(p, "first_name", f"kind={k}"))
        msg = await raw.send_contact(
            chat_id,
            phone,
            first_name,
            last_name=p.get("last_name"),
            vcard=p.get("vcard"),
            reply_parameters=reply,
            message_thread_id=message_thread_id,
        )
    elif k == "dice":
        emoji = str(p.get("emoji") or "🎲")
        msg = await raw.send_dice(
            chat_id,
            emoji=emoji,
            reply_parameters=reply,
            message_thread_id=message_thread_id,
        )
    elif k == "checklist":
        title = str(_req(p, "title", f"kind={k}"))
        raw_tasks = _req(p, "tasks", f"kind={k}")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise McpError(INTERNAL, "checklist 的 tasks 需为非空列表")
        pm = _parse_mode(p.get("parse_mode", "none"))
        tasks: list[InputChecklistTask] = []
        for idx, t in enumerate(raw_tasks, start=1):
            if isinstance(t, str):
                tasks.append(InputChecklistTask(id=idx, text=t, parse_mode=pm))
            elif isinstance(t, dict):
                txt = t.get("text")
                if not txt:
                    raise McpError(INTERNAL, f"checklist 第 {idx} 项缺少 text")
                tasks.append(InputChecklistTask(id=int(t.get("id", idx)), text=str(txt), parse_mode=pm))
            else:
                raise McpError(INTERNAL, f"checklist 任务项类型不支持: {type(t).__name__}")
        checklist = InputChecklist(
            title=title,
            tasks=tasks,
            parse_mode=pm,
            others_can_add_tasks=p.get("others_can_add_tasks"),
            others_can_mark_tasks_as_done=p.get("others_can_mark_tasks_as_done"),
        )
        msg = await raw.send_checklist(
            chat_id,
            checklist,
            reply_parameters=reply,
            message_thread_id=message_thread_id,
        )
    else:
        raise McpError(INTERNAL, f"不支持的 kind: {kind}(支持: {', '.join(EXTRA_SEND_KINDS)})")

    if msg is None:
        raise McpError(INTERNAL, f"send_extra({k}) 未返回消息")
    return message_view(msg)


async def manage_message_extras(
    client: TelegramClient,
    chat_id: int,
    action: str,
    params: dict[str, Any] | None = None,
) -> dict:
    """消息扩展操作:置顶/取消置顶/勾选清单任务。"""
    p = params or {}
    act = action.strip().lower()
    raw = client.raw

    if act == "pin":
        mid = int(_req(p, "message_id", f"action={act}"))
        msg = await raw.pin_chat_message(
            chat_id,
            mid,
            disable_notification=bool(p.get("disable_notification", False)),
            both_sides=bool(p.get("both_sides", False)),
        )
        return {
            "chat_id": chat_id,
            "message_id": mid,
            "pinned": True,
            "service_message": message_view(msg) if msg is not None else None,
        }

    if act == "unpin":
        mid = int(p.get("message_id", 0))
        ok = await raw.unpin_chat_message(chat_id, mid)
        return {"chat_id": chat_id, "message_id": mid, "unpinned": bool(ok)}

    if act == "mark_checklist":
        mid = int(_req(p, "message_id", f"action={act}"))
        done_ids = p.get("done_task_ids")
        not_done_ids = p.get("not_done_task_ids")
        if done_ids is None and not_done_ids is None:
            raise McpError(INTERNAL, "mark_checklist 至少需要 done_task_ids 或 not_done_task_ids 之一")
        res = await raw.mark_checklist_tasks_as_done(
            chat_id,
            mid,
            marked_as_done_task_ids=[int(x) for x in done_ids] if done_ids is not None else None,
            marked_as_not_done_task_ids=[int(x) for x in not_done_ids] if not_done_ids is not None else None,
        )
        return {"chat_id": chat_id, "message_id": mid, "updated": True, "result": res}

    raise McpError(INTERNAL, f"未知的 action: {action}(支持: {', '.join(EXTRA_MSG_ACTIONS)})")
