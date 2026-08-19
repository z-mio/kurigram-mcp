"""views 序列化测试。"""

from __future__ import annotations

import types

from kurigram_mcp.telegram.views import markup_view, message_view


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
        "reply_to_message_id": None,
        "service": None,
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
