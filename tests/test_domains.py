"""领域聚合工具与 --toolsets 分组测试:stickers / forum / extras / inline_bot_result。"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest
from pyrogram.enums import MaskPointType, StickerFormat, StickerType
from pyrogram.types import InputChecklist, InputSticker, MaskPosition, ReplyParameters

from kurigram_mcp.config import VALID_TOOLSETS, Settings, parse_toolsets
from kurigram_mcp.errors import McpError
from kurigram_mcp.server import build_server
from kurigram_mcp.telegram.client import TelegramClient
from kurigram_mcp.telegram.extras import manage_message_extras, send_extra
from kurigram_mcp.telegram.forum import manage_forum_topics
from kurigram_mcp.telegram.stickers import stickers_manage, stickers_query


def _fake_sticker(fid: str = "st_1") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        file_id=fid,
        file_unique_id="u_" + fid,
        type=StickerType.REGULAR,
        width=512,
        height=512,
        is_animated=False,
        is_video=False,
        emoji="😀",
        set_name="demo_set",
        custom_emoji_id=None,
        file_name="s.webp",
        mime_type="image/webp",
        file_size=1234,
        needs_repainting=False,
        mask_position=None,
    )


def _fake_sticker_set(name: str = "demo_set") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=999,
        name=name,
        title="Demo Set",
        sticker_type=StickerType.REGULAR,
        stickers=[_fake_sticker()],
        is_owned=True,
        is_installed=True,
        is_archived=False,
        is_official=False,
        needs_repainting=False,
    )


def _fake_topic(tid: int = 12, name: str = "General") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=tid,
        name=name,
        date=None,
        icon_color=0x6FB9F0,
        icon_custom_emoji_id=None,
        is_my=True,
        is_closed=False,
        is_pinned=False,
        is_hidden=False,
        unread_count=0,
        top_message=types.SimpleNamespace(id=500),
    )


def _fake_msg(**overrides: Any) -> types.SimpleNamespace:
    base: dict[str, Any] = {
        "id": 77,
        "chat": types.SimpleNamespace(id=100),
        "date": None,
        "edit_date": None,
        "out": True,
        "from_user": None,
        "text": None,
        "caption": None,
        "media": None,
        "media_group_id": None,
        "poll": None,
        "checklist": None,
        "dice": None,
        "reply_to_message_id": None,
        "service": None,
        "reply_markup": None,
        "raw": None,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


class RecordingDomainRaw:
    """记录所有 stickers / forum / extras / inline 调用实参的假 pyrogram Client。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _rec(self, method: str, /, *args: Any, **kw: Any) -> None:
        self.calls.append((method, args, kw))

    # --- stickers query ---
    async def get_sticker_set(self, name: str):
        self._rec("get_sticker_set", name)
        return _fake_sticker_set(name)

    def get_owned_sticker_sets(self, **kw: Any):
        self._rec("get_owned_sticker_sets", **kw)

        async def gen():
            yield _fake_sticker_set("owned_1")

        return gen()

    async def get_custom_emoji_stickers(self, ids: list[str]):
        self._rec("get_custom_emoji_stickers", ids)
        return [_fake_sticker("ce_1")]

    def search_stickers(self, *args: Any, **kw: Any):
        self._rec("search_stickers", *args, **kw)

        async def gen():
            yield _fake_sticker("found_1")

        return gen()

    async def search_sticker_sets(self, *args: Any):
        self._rec("search_sticker_sets", *args)
        return [_fake_sticker_set("found_set")]

    async def get_favorite_stickers(self):
        self._rec("get_favorite_stickers")
        return [_fake_sticker("fav_1")]

    async def get_recent_stickers(self, **kw: Any):
        self._rec("get_recent_stickers", **kw)
        return [_fake_sticker("rec_1")]

    async def get_suggested_sticker_set_name(self, title: str):
        self._rec("get_suggested_sticker_set_name", title)
        return "suggested_set"

    # --- stickers manage ---
    async def change_sticker_set(self, name: str, **kw: Any):
        self._rec("change_sticker_set", name, **kw)
        return True

    async def reorder_installed_sticker_sets(self, *args: Any):
        self._rec("reorder_installed_sticker_sets", *args)
        return True

    async def add_favorite_sticker(self, sticker: str):
        self._rec("add_favorite_sticker", sticker)
        return True

    async def remove_favorite_sticker(self, sticker: str):
        self._rec("remove_favorite_sticker", sticker)
        return True

    async def add_recent_sticker(self, sticker: str, **kw: Any):
        self._rec("add_recent_sticker", sticker, **kw)
        return True

    async def remove_recent_sticker(self, sticker: str, **kw: Any):
        self._rec("remove_recent_sticker", sticker, **kw)
        return True

    async def clear_recent_stickers(self, **kw: Any):
        self._rec("clear_recent_stickers", **kw)
        return True

    async def create_new_sticker_set(self, **kw: Any):
        self._rec("create_new_sticker_set", **kw)
        return _fake_sticker_set(kw["name"])

    async def add_sticker_to_set(self, **kw: Any):
        self._rec("add_sticker_to_set", **kw)
        return _fake_sticker_set(kw["name"])

    async def replace_sticker_in_set(self, **kw: Any):
        self._rec("replace_sticker_in_set", **kw)
        return _fake_sticker_set()

    async def delete_sticker_from_set(self, sticker: str):
        self._rec("delete_sticker_from_set", sticker)
        return _fake_sticker_set()

    async def delete_sticker_set(self, name: str):
        self._rec("delete_sticker_set", name)
        return True

    async def set_sticker_set_title(self, name: str, title: str):
        self._rec("set_sticker_set_title", name, title)
        return _fake_sticker_set(name)

    async def set_sticker_set_thumbnail(self, **kw: Any):
        self._rec("set_sticker_set_thumbnail", **kw)
        return _fake_sticker_set(kw["name"])

    async def set_custom_emoji_sticker_set_thumbnail(self, name: str, **kw: Any):
        self._rec("set_custom_emoji_sticker_set_thumbnail", name, **kw)
        return _fake_sticker_set(name)

    async def set_sticker_emoji_list(self, sticker: str, emojis: list[str]):
        self._rec("set_sticker_emoji_list", sticker, emojis)
        return _fake_sticker_set()

    async def set_sticker_keywords(self, sticker: str, keywords: Any):
        self._rec("set_sticker_keywords", sticker, keywords)
        return _fake_sticker_set()

    async def set_sticker_mask_position(self, sticker: str, mp: Any):
        self._rec("set_sticker_mask_position", sticker, mp)
        return _fake_sticker_set()

    async def set_sticker_position_in_set(self, sticker: str, pos: int):
        self._rec("set_sticker_position_in_set", sticker, pos)
        return _fake_sticker_set()

    async def upload_sticker_file(self, **kw: Any):
        self._rec("upload_sticker_file", **kw)
        return types.SimpleNamespace(file_id="up_fid", file_unique_id="up_uid", file_size=2048)

    # --- forum ---
    def get_forum_topics(self, chat_id: int, **kw: Any):
        self._rec("get_forum_topics", chat_id, **kw)

        async def gen():
            yield _fake_topic(10, "Topic A")

        return gen()

    async def get_forum_topics_by_id(self, chat_id: int, ids: list[int]):
        self._rec("get_forum_topics_by_id", chat_id, ids)
        return [_fake_topic(i, f"T{i}") for i in ids]

    async def create_forum_topic(self, chat_id: int, name: str, **kw: Any):
        self._rec("create_forum_topic", chat_id, name, **kw)
        return _fake_topic(99, name)

    async def edit_forum_topic(self, chat_id: int, tid: int, **kw: Any):
        self._rec("edit_forum_topic", chat_id, tid, **kw)
        return True

    async def close_forum_topic(self, chat_id: int, tid: int):
        self._rec("close_forum_topic", chat_id, tid)
        return True

    async def reopen_forum_topic(self, chat_id: int, tid: int):
        self._rec("reopen_forum_topic", chat_id, tid)
        return True

    async def delete_forum_topic(self, chat_id: int, tid: int):
        self._rec("delete_forum_topic", chat_id, tid)
        return True

    async def pin_forum_topic(self, chat_id: int, tid: int):
        self._rec("pin_forum_topic", chat_id, tid)
        return True

    async def unpin_forum_topic(self, chat_id: int, tid: int):
        self._rec("unpin_forum_topic", chat_id, tid)
        return True

    async def hide_general_forum_topic(self, chat_id: int):
        self._rec("hide_general_forum_topic", chat_id)
        return True

    async def unhide_general_forum_topic(self, chat_id: int):
        self._rec("unhide_general_forum_topic", chat_id)
        return True

    async def unpin_all_forum_topic_messages(self, chat_id: int, tid: int):
        self._rec("unpin_all_forum_topic_messages", chat_id, tid)
        return True

    async def toggle_forum_topics(self, chat_id: int, **kw: Any):
        self._rec("toggle_forum_topics", chat_id, **kw)
        return True

    # --- extras ---
    async def send_video(self, chat_id: int, media: str, **kw: Any):
        self._rec("send_video", chat_id, media, **kw)
        return _fake_msg(media=types.SimpleNamespace(value="VIDEO"))

    async def send_animation(self, chat_id: int, media: str, **kw: Any):
        self._rec("send_animation", chat_id, media, **kw)
        return _fake_msg(media=types.SimpleNamespace(value="ANIMATION"))

    async def send_audio(self, chat_id: int, media: str, **kw: Any):
        self._rec("send_audio", chat_id, media, **kw)
        return _fake_msg(media=types.SimpleNamespace(value="AUDIO"))

    async def send_location(self, chat_id: int, lat: float, lon: float, **kw: Any):
        self._rec("send_location", chat_id, lat, lon, **kw)
        return _fake_msg(media=types.SimpleNamespace(value="LOCATION"))

    async def send_contact(self, chat_id: int, phone: str, first_name: str, **kw: Any):
        self._rec("send_contact", chat_id, phone, first_name, **kw)
        return _fake_msg(media=types.SimpleNamespace(value="CONTACT"))

    async def send_dice(self, chat_id: int, **kw: Any):
        self._rec("send_dice", chat_id, **kw)
        return _fake_msg(dice=types.SimpleNamespace(emoji=kw["emoji"], value=6))

    async def send_checklist(self, chat_id: int, checklist: InputChecklist, **kw: Any):
        self._rec("send_checklist", chat_id, checklist, **kw)
        return _fake_msg(
            checklist=types.SimpleNamespace(
                title=checklist.title,
                tasks=[types.SimpleNamespace(id=t.id, text=t.text, completion_date=None) for t in checklist.tasks],
                others_can_add_tasks=True,
                others_can_mark_tasks_as_done=True,
            )
        )

    async def pin_chat_message(self, chat_id: int, mid: int, **kw: Any):
        self._rec("pin_chat_message", chat_id, mid, **kw)
        return _fake_msg(id=88)

    async def unpin_chat_message(self, chat_id: int, mid: int):
        self._rec("unpin_chat_message", chat_id, mid)
        return True

    async def mark_checklist_tasks_as_done(self, chat_id: int, mid: int, **kw: Any):
        self._rec("mark_checklist_tasks_as_done", chat_id, mid, **kw)
        return 1

    # --- inline ---
    async def get_inline_bot_results(self, bot: str, **kw: Any):
        self._rec("get_inline_bot_results", bot, **kw)
        return types.SimpleNamespace(
            query_id=9007199254740993123,
            gallery=False,
            cache_time=10,
            next_offset="",
            switch_pm=None,
            results=[types.SimpleNamespace(id="r1", type="article", title="Res1")],
        )

    async def send_inline_bot_result(self, chat_id: int, qid: int, rid: str, **kw: Any):
        self._rec("send_inline_bot_result", chat_id, qid, rid, **kw)
        return _fake_msg(text="inline sent")


def _client(raw: RecordingDomainRaw, uploads_dir: Path | None = None) -> TelegramClient:
    tc = TelegramClient.__new__(TelegramClient)
    tc.settings = types.SimpleNamespace(uploads_dir=uploads_dir)
    tc._client = raw
    tc._me = types.SimpleNamespace(id=4242)
    return tc


# ---------- 1. toolsets 配置与按需注册 ----------


def test_parse_toolsets_variants() -> None:
    assert parse_toolsets(None) == VALID_TOOLSETS
    assert parse_toolsets("") == VALID_TOOLSETS
    assert parse_toolsets("all") == VALID_TOOLSETS
    assert parse_toolsets("core, stickers , core") == ("core", "stickers")
    assert parse_toolsets("forum,all") == VALID_TOOLSETS
    with pytest.raises(McpError, match="未知的 toolset"):
        parse_toolsets("core,unknown_group")


def test_build_server_respects_toolsets() -> None:
    s = Settings()
    all_names = {t.name for t in build_server(s, toolsets="all")._tool_manager.list_tools()}
    assert {
        "send_message",
        "send_inline_bot_result",
        "stickers_query",
        "stickers_manage",
        "manage_forum_topics",
        "send_extra",
        "manage_message_extras",
        "raw_invoke",
        "whoami",
        "mcp_get_server_info",
    }.issubset(all_names)

    core_only = {t.name for t in build_server(s, toolsets="core")._tool_manager.list_tools()}
    assert "send_message" in core_only and "send_inline_bot_result" in core_only
    assert "whoami" in core_only and "mcp_get_server_info" in core_only
    assert "stickers_query" not in core_only
    assert "manage_forum_topics" not in core_only
    assert "send_extra" not in core_only
    assert "raw_invoke" not in core_only

    stickers_only = {t.name for t in build_server(s, toolsets="stickers")._tool_manager.list_tools()}
    assert stickers_only == {"stickers_query", "stickers_manage", "whoami", "mcp_get_server_info"}


def test_tool_schema_quality_guards() -> None:
    """守卫工具描述与 schema 质量:全局 instructions、cleandoc 去缩进、enum 约束与 annotations。"""
    mcp = build_server(Settings(), toolsets="all")
    assert mcp.instructions and "params" in mcp.instructions and "account" in mcp.instructions

    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    # 所有描述经 cleandoc 清理,不应残留 4+ 空格缩进
    for name, tool in tools.items():
        assert tool.description and "\n    " not in tool.description, f"{name} 含未清理缩进"

    # 关键枚举参数必须生成 JSON Schema enum
    for name, param in (
        ("stickers_query", "action"),
        ("stickers_manage", "action"),
        ("manage_forum_topics", "action"),
        ("send_extra", "kind"),
        ("manage_message_extras", "action"),
        ("send_chat_action", "action"),
        ("send_message", "parse_mode"),
        ("send_rich_message", "format"),
    ):
        prop = tools[name].parameters["properties"][param]
        assert "enum" in prop, f"{name}.{param} 缺少 JSON Schema enum"

    # 只读 / 破坏性注解
    for ro in ("whoami", "mcp_get_server_info", "get_chat", "stickers_query", "list_raw_methods"):
        assert tools[ro].annotations and tools[ro].annotations.read_only_hint is True, ro
    for dest in ("delete_message", "leave_chat", "raw_invoke"):
        assert tools[dest].annotations and tools[dest].annotations.destructive_hint is True, dest


# ---------- 2. stickers 全部 28 个方法 ----------


@pytest.mark.asyncio
async def test_stickers_query_all_actions() -> None:
    raw = RecordingDomainRaw()
    tc = _client(raw)

    assert (await stickers_query(tc, "get_set", {"name": "s1"}))["name"] == "s1"
    assert (await stickers_query(tc, "get_owned_sets", {"limit": 5}))["count"] == 1
    assert (await stickers_query(tc, "get_custom_emoji", {"custom_emoji_ids": ["111"]}))["count"] == 1
    assert (await stickers_query(tc, "search", {"emojis": ["😀"], "query": "cat"}))["count"] == 1
    assert (await stickers_query(tc, "search_sets", {"query": "cat"}))["count"] == 1
    assert (await stickers_query(tc, "favorites"))["count"] == 1
    assert (await stickers_query(tc, "recent", {"is_attached": False}))["count"] == 1
    assert (await stickers_query(tc, "suggest_name", {"title": "Cats"}))["name"] == "suggested_set"

    with pytest.raises(McpError, match="未知的 stickers_query"):
        await stickers_query(tc, "nope")
    with pytest.raises(McpError, match="缺少必填参数"):
        await stickers_query(tc, "get_set", {})


@pytest.mark.asyncio
async def test_stickers_manage_all_actions_and_upload_ref(tmp_path: Path) -> None:
    uid = "a" * 16
    up_dir = tmp_path / uid
    up_dir.mkdir()
    staged = up_dir / "cat.webp"
    staged.write_bytes(b"RIFF")

    raw = RecordingDomainRaw()
    tc = _client(raw, uploads_dir=tmp_path)

    assert (await stickers_manage(tc, "install", {"name": "s1"}))["ok"] is True
    assert (await stickers_manage(tc, "uninstall", {"name": "s1"}))["ok"] is True
    assert (await stickers_manage(tc, "archive", {"name": "s1"}))["ok"] is True
    assert (await stickers_manage(tc, "reorder_sets", {"sticker_set_ids": [1, 2]}))["ok"] is True
    assert (await stickers_manage(tc, "add_favorite", {"sticker": "fid"}))["ok"] is True
    assert (await stickers_manage(tc, "remove_favorite", {"sticker": "fid"}))["ok"] is True
    assert (await stickers_manage(tc, "add_recent", {"sticker": "fid"}))["ok"] is True
    assert (await stickers_manage(tc, "remove_recent", {"sticker": "fid"}))["ok"] is True
    assert (await stickers_manage(tc, "clear_recent"))["ok"] is True

    sticker_spec = {
        "sticker": f"upload://{uid}/cat.webp",
        "format": "static",
        "emoji_list": ["😺"],
        "mask_position": {"point": "forehead", "x_shift": 0.1, "y_shift": -0.2, "scale": 1.5},
        "keywords": ["cat"],
    }
    res = await stickers_manage(tc, "create_set", {"name": "my_set", "title": "My Set", "stickers": [sticker_spec]})
    assert res["name"] == "my_set"
    create_kw = next(kw for n, _, kw in raw.calls if n == "create_new_sticker_set")
    assert create_kw["user_id"] == 4242  # 默认取当前账号
    st_obj = create_kw["stickers"][0]
    assert isinstance(st_obj, InputSticker)
    assert st_obj.sticker == str(staged)  # upload:// 已解析
    assert st_obj.format == StickerFormat.STATIC
    assert isinstance(st_obj.mask_position, MaskPosition) and st_obj.mask_position.point == MaskPointType.FOREHEAD

    await stickers_manage(tc, "add_to_set", {"name": "my_set", "sticker": sticker_spec})
    await stickers_manage(tc, "replace_in_set", {"old_sticker": "old_fid", "sticker": sticker_spec})
    await stickers_manage(tc, "delete_from_set", {"sticker": "fid"})
    await stickers_manage(tc, "delete_set", {"name": "my_set"})
    await stickers_manage(tc, "set_title", {"name": "my_set", "title": "New Title"})
    await stickers_manage(
        tc, "set_thumbnail", {"name": "my_set", "format": "static", "thumbnail": f"upload://{uid}/cat.webp"}
    )
    await stickers_manage(tc, "set_custom_emoji_thumbnail", {"name": "my_set", "custom_emoji_id": "999"})
    await stickers_manage(tc, "set_emoji_list", {"sticker": "fid", "emoji_list": ["🔥"]})
    await stickers_manage(tc, "set_keywords", {"sticker": "fid", "keywords": ["fire"]})
    await stickers_manage(
        tc,
        "set_mask_position",
        {"sticker": "fid", "mask_position": {"point": "eyes", "x_shift": 0, "y_shift": 0, "scale": 1}},
    )
    await stickers_manage(tc, "set_position", {"sticker": "fid", "position": 0})
    up = await stickers_manage(tc, "upload_file", {"sticker": f"upload://{uid}/cat.webp", "format": "static"})
    assert up["file_id"] == "up_fid"

    with pytest.raises(McpError, match="未知的 stickers_manage"):
        await stickers_manage(tc, "bad")


# ---------- 3. forum 全部 13 个方法 ----------


@pytest.mark.asyncio
async def test_manage_forum_topics_all_actions() -> None:
    raw = RecordingDomainRaw()
    tc = _client(raw)

    assert (await manage_forum_topics(tc, -1001, "list", {"limit": 10}))["count"] == 1
    assert (await manage_forum_topics(tc, -1001, "get_by_id", {"topic_ids": [1, 2]}))["count"] == 2
    assert (await manage_forum_topics(tc, -1001, "create", {"name": "Bugs"}))["topic"]["name"] == "Bugs"
    assert (await manage_forum_topics(tc, -1001, "edit", {"message_thread_id": 10, "name": "Fixed"}))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "close", {"message_thread_id": 10}))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "reopen", {"message_thread_id": 10}))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "delete", {"message_thread_id": 10}))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "pin", {"message_thread_id": 10}))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "unpin", {"message_thread_id": 10}))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "hide_general"))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "unhide_general"))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "unpin_all_messages", {"message_thread_id": 10}))["ok"] is True
    assert (await manage_forum_topics(tc, -1001, "toggle", {"is_forum": True, "has_forum_sidebar": True}))["ok"] is True

    with pytest.raises(McpError, match="未知的 forum action"):
        await manage_forum_topics(tc, -1001, "nope")


# ---------- 4. extras 扩展发送与消息操作 ----------


@pytest.mark.asyncio
async def test_send_extra_and_manage_message_extras(tmp_path: Path) -> None:
    uid = "b" * 16
    up_dir = tmp_path / uid
    up_dir.mkdir()
    vid = up_dir / "v.mp4"
    vid.write_bytes(b"mp4")

    raw = RecordingDomainRaw()
    tc = _client(raw, uploads_dir=tmp_path)

    await send_extra(
        tc,
        100,
        "video",
        {"media": f"upload://{uid}/v.mp4", "caption": "hi"},
        reply_to_message_id=5,
        message_thread_id=12,
    )
    _, args, kw = raw.calls[-1]
    assert args == (100, str(vid))
    assert isinstance(kw["reply_parameters"], ReplyParameters) and kw["reply_parameters"].message_id == 5
    assert kw["message_thread_id"] == 12

    await send_extra(tc, 100, "animation", {"media": "a.gif"})
    await send_extra(tc, 100, "audio", {"media": "a.mp3", "performer": "P", "title": "T"})
    await send_extra(tc, 100, "location", {"latitude": 31.2, "longitude": 121.5})
    await send_extra(tc, 100, "contact", {"phone_number": "+123", "first_name": "Bob"})

    dice_res = await send_extra(tc, 100, "dice", {"emoji": "🎯"})
    assert dice_res["dice"] == {"emoji": "🎯", "value": 6}

    cl_res = await send_extra(tc, 100, "checklist", {"title": "Todo", "tasks": ["A", {"id": 5, "text": "B"}]})
    assert cl_res["checklist"]["title"] == "Todo"
    assert [t["id"] for t in cl_res["checklist"]["tasks"]] == [1, 5]

    pin_res = await manage_message_extras(tc, 100, "pin", {"message_id": 77, "both_sides": True})
    assert pin_res["pinned"] is True and pin_res["service_message"]["message_id"] == 88
    assert (await manage_message_extras(tc, 100, "unpin", {"message_id": 77}))["unpinned"] is True
    assert (await manage_message_extras(tc, 100, "mark_checklist", {"message_id": 77, "done_task_ids": [1]}))[
        "updated"
    ] is True

    with pytest.raises(McpError, match="不支持的 kind"):
        await send_extra(tc, 100, "invalid")
    with pytest.raises(McpError, match="至少需要"):
        await manage_message_extras(tc, 100, "mark_checklist", {"message_id": 77})


# ---------- 5. inline query_id 与 send_inline_bot_result ----------


@pytest.mark.asyncio
async def test_inline_query_returns_str_query_id_and_send_result() -> None:
    raw = RecordingDomainRaw()
    tc = _client(raw)

    res = await tc.send_inline_query("@demo_bot", query="hello")
    assert res["query_id"] == "9007199254740993123"

    sent = await tc.send_inline_bot_result(100, res["query_id"], "r1", reply_to_message_id=9, message_thread_id=15)
    assert sent["text"] == "inline sent"
    name, args, kw = raw.calls[-1]
    assert name == "send_inline_bot_result"
    assert args == (100, 9007199254740993123, "r1")
    assert kw["reply_parameters"].message_id == 9 and kw["message_thread_id"] == 15
