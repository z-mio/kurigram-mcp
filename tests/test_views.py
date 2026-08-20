"""views 序列化测试。"""

from __future__ import annotations

import types

from kurigram_mcp.telegram.views import (
    inline_result_view,
    markup_view,
    message_view,
    poll_view,
)


def make_msg(**overrides) -> types.SimpleNamespace:
    base = {
        "id": 42,
        "chat": types.SimpleNamespace(id=6540476263),
        "date": None,
        "edit_date": None,
        "out": True,
        "from_user": None,
        "text": "hello",
        "caption": None,
        "media": None,
        "media_group_id": None,
        "poll": None,
        "reply_to_message_id": None,
        "service": None,
        "reply_markup": None,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_message_view_plain() -> None:
    v = message_view(make_msg())
    assert v["message_id"] == 42
    assert v["chat_id"] == 6540476263
    assert v["text"] == "hello"
    assert v["from"] is None
    assert v["media"] is None


def test_message_view_with_sender_and_media() -> None:
    msg = make_msg(
        from_user=types.SimpleNamespace(id=1, username="zl_ing", first_name="zio", is_bot=False),
        media=types.SimpleNamespace(value="PHOTO"),
        text=None,
        caption="cap",
    )
    v = message_view(msg)
    assert v["text"] == "cap"
    assert v["media"] == "PHOTO"
    assert v["from"]["username"] == "zl_ing"
    assert v["from"]["is_bot"] is False


def test_message_view_bot_sender() -> None:
    msg = make_msg(
        from_user=types.SimpleNamespace(
            id=6540476263, username="GLBetabot", first_name="GL Beta", is_bot=True
        )
    )
    assert msg and message_view(msg)["from"]["is_bot"] is True


def test_markup_view_inline() -> None:
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("点我", callback_data=b"btn_1"),
                InlineKeyboardButton("官网", url="https://x.com"),
            ],
            [InlineKeyboardButton("下一行", callback_data=b"btn_2")],
        ]
    )
    v = markup_view(markup)
    assert v["type"] == "inline"
    assert v["rows"][0][0] == {"text": "点我", "callback_data": "btn_1"}
    assert v["rows"][0][1] == {"text": "官网", "url": "https://x.com"}
    assert v["rows"][1][0]["callback_data"] == "btn_2"


def test_markup_view_reply_keyboard() -> None:
    from pyrogram.types import KeyboardButton, ReplyKeyboardMarkup

    markup = ReplyKeyboardMarkup([[KeyboardButton("帮助")]])
    v = markup_view(markup)
    assert v["type"] == "reply"
    assert v["rows"] == [[{"text": "帮助"}]]


def test_markup_view_none() -> None:
    assert markup_view(None) is None


def test_message_view_media_group_and_poll() -> None:
    """相册消息应带 media_group_id;投票消息应带 poll 摘要。"""
    poll = types.SimpleNamespace(
        id="5959268912454516736",
        question="今天吃啥?",
        options=[
            types.SimpleNamespace(text="火锅", voter_count=3, data=b"0"),
            types.SimpleNamespace(text="烧烤", voter_count=1, data=b"1"),
        ],
        total_voters=4,
        is_closed=False,
        is_anonymous=True,
        type=types.SimpleNamespace(value="REGULAR"),
    )
    msg = make_msg(media_group_id=777777, poll=poll, text=None)
    v = message_view(msg)
    assert v["media_group_id"] == 777777
    assert v["poll"]["question"] == "今天吃啥?"
    assert v["poll"]["options"] == [
        {"text": "火锅", "voters": 3, "data": b"0"},
        {"text": "烧烤", "voters": 1, "data": b"1"},
    ]
    assert v["poll"]["total_voters"] == 4
    assert v["poll"]["type"] == "REGULAR"


def test_poll_view_voter_count_fallback() -> None:
    """kurigram 新版属性是 voter_count;旧版 voters 应兜底,不能恒为 0。"""
    import datetime

    from kurigram_mcp.telegram.views import poll_view

    # 新版:voter_count
    poll = types.SimpleNamespace(
        id="1", question="q", options=[types.SimpleNamespace(text="A", voter_count=5, data=None)],
        total_voters=5, is_closed=False, is_anonymous=True, type=types.SimpleNamespace(value="REGULAR"),
    )
    assert poll_view(poll)["options"][0]["voters"] == 5
    # 旧版兜底:voters
    poll2 = types.SimpleNamespace(
        id="2", question="q", options=[types.SimpleNamespace(text="A", voters=2, data=None)],
        total_voters=2, is_closed=False, is_anonymous=True, type=types.SimpleNamespace(value="REGULAR"),
    )
    assert poll_view(poll2)["options"][0]["voters"] == 2
    # 都没有 -> 0
    poll3 = types.SimpleNamespace(
        id="3", question="q", options=[types.SimpleNamespace(text="A", data=None)],
        total_voters=0, is_closed=False, is_anonymous=True, type=types.SimpleNamespace(value="REGULAR"),
    )
    assert poll_view(poll3)["options"][0]["voters"] == 0
    assert datetime is not None


def test_message_view_no_poll() -> None:
    assert message_view(make_msg())["poll"] is None


def test_message_view_outgoing_alias_and_utc_suffix() -> None:
    """out 应有 is_outgoing 别名;naive UTC 日期应补 Z 后缀。"""
    import datetime

    msg = make_msg(
        out=True,
        date=datetime.datetime(2026, 8, 20, 11, 4, 19, tzinfo=datetime.UTC).replace(tzinfo=None),  # naive UTC
        edit_date=datetime.datetime(2026, 8, 20, 11, 5, 0, tzinfo=datetime.UTC),
    )
    v = message_view(msg)
    assert v["out"] is True and v["is_outgoing"] is True
    assert v["date"] == "2026-08-20T11:04:19Z"
    assert v["edit_date"] == "2026-08-20T11:05:00+00:00"
    # 无日期 -> None,不崩
    assert message_view(make_msg())["date"] is None


def test_poll_view_none() -> None:
    assert poll_view(None) is None


def test_message_view_entities_summary() -> None:
    """实体摘要:bold/custom_emoji 等非 url 实体也应可见(验证格式是否生效/被降级)。"""
    msg = make_msg(text="粗体内容")
    msg.entities = [
        types.SimpleNamespace(type="bold", offset=0, length=2, url=None),
        types.SimpleNamespace(type="custom_emoji", offset=0, length=2, url=None),
    ]
    v = message_view(msg)
    assert v["entities"] == [
        {"type": "bold", "text": "粗体"},
        {"type": "custom_emoji", "text": "粗体"},
    ]
    # 无实体 -> None
    assert message_view(make_msg())["entities"] is None


def test_message_view_links() -> None:
    """子会话实测场景:bot 回复 "WIKI" 实际是超链接——视图应暴露 links。"""
    entity = types.SimpleNamespace(
        type="url", offset=9, length=4, url="https://wiki.getletbot.com/"
    )
    msg = make_msg(text="Bot使用文档: WIKI", caption=None)
    msg.entities = [entity]
    v = message_view(msg)
    assert v["links"] == [
        {"text": "WIKI", "url": "https://wiki.getletbot.com/", "type": "url"}
    ]
    # 无实体 -> None,不崩
    msg2 = make_msg(text="没有链接")
    msg2.entities = None
    assert message_view(msg2)["links"] is None
    # 无 url 的实体(如 bold)不输出
    msg3 = make_msg(text="加粗")
    msg3.entities = [types.SimpleNamespace(type="bold", offset=0, length=2, url=None)]
    assert message_view(msg3)["links"] is None


def test_inline_result_view() -> None:
    """内联查询结果序列化:标题/描述/URL/缩略图/消息内容。"""
    result = types.SimpleNamespace(
        id="r1",
        type="article",
        title="结果一",
        description="说明",
        url="https://example.com/1",
        thumb=types.SimpleNamespace(url="https://example.com/thumb.png"),
        send_message=types.SimpleNamespace(message="点我发送这条消息"),
    )
    v = inline_result_view(result)
    assert v == {
        "id": "r1",
        "type": "article",
        "title": "结果一",
        "description": "说明",
        "url": "https://example.com/1",
        "thumb_url": "https://example.com/thumb.png",
        "message": "点我发送这条消息",
    }
    # 无缩略图/无消息内容的媒体结果也不应崩
    media = types.SimpleNamespace(
        id="r2", type="photo", title=None, description=None, url=None, thumb=None, send_message=None
    )
    assert inline_result_view(media)["thumb_url"] is None
