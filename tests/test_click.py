"""click_inline_button:富消息(rich_message)按钮 + inline 键盘回归。

复用 test_kurigram_compat 的 _client 模式:TelegramClient.__new__ + 假 raw client。
"""

from __future__ import annotations

import types

import pytest
from pyrogram.raw.types import (
    InlineButtonTypeCallback,
    InlineButtonTypeUrl,
    PageBlockButtonRow,
    PageButton,
    RichMessage,
    TextPlain,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from test_kurigram_compat import _client

from kurigram_mcp.errors import McpError


class FakeRaw:
    """记录 invoke 实参的假 Client(只实现 click_inline_button 用到的方法)。"""

    def __init__(self, message) -> None:
        self.message = message
        self.invoked: list = []

    async def get_messages(self, chat_id, message_id):
        return self.message

    async def resolve_peer(self, chat_id):
        return object()  # peer 哨兵

    async def invoke(self, query):
        self.invoked.append(query)
        return types.SimpleNamespace(alert=False, has_url=False, message="ok", url=None, cache_time=0)


def _rich_msg(buttons, reply_markup=None):
    """带富消息按钮行的消息替身。"""
    return types.SimpleNamespace(
        reply_markup=reply_markup,
        raw=types.SimpleNamespace(
            rich_message=RichMessage(
                blocks=[PageBlockButtonRow(buttons=buttons)],
                photos=[],
                documents=[],
            )
        ),
        edit_date=None,
    )


@pytest.mark.asyncio
async def test_click_rich_callback_by_data() -> None:
    """data 命中富消息 callback 按钮 → GetBotCallbackAnswer。"""
    raw = FakeRaw(_rich_msg([PageButton(text=TextPlain(text="OK"), type=InlineButtonTypeCallback(data=b"act:1"))]))
    out = await _client(raw).click_inline_button(1, 42, data="act:1")
    assert out["type"] == "callback" and out["source"] == "rich" and out["text"] == "OK"
    assert len(raw.invoked) == 1
    q = raw.invoked[0]
    assert type(q).__name__ == "GetBotCallbackAnswer"
    assert q.data == b"act:1" and q.msg_id == 42


@pytest.mark.asyncio
async def test_click_rich_url_button_by_text() -> None:
    raw = FakeRaw(_rich_msg([PageButton(text=TextPlain(text="Docs"), type=InlineButtonTypeUrl(url="https://d"))]))
    out = await _client(raw).click_inline_button(1, 42, button_text="Docs")
    assert out == {"type": "url", "text": "Docs", "url": "https://d", "source": "rich"}
    assert raw.invoked == []


@pytest.mark.asyncio
async def test_click_row_col_addresses_rich_rows() -> None:
    """没有 inline 键盘时 row/col 按 rich.buttons 寻址。"""
    raw = FakeRaw(
        _rich_msg(
            [
                PageButton(text=TextPlain(text="A"), type=InlineButtonTypeUrl(url="https://a")),
                PageButton(text=TextPlain(text="B"), type=InlineButtonTypeCallback(data=b"b")),
            ]
        )
    )
    out = await _client(raw).click_inline_button(1, 42, row_index=0, col_index=1)
    assert out["type"] == "callback" and out["text"] == "B" and out["source"] == "rich"
    assert raw.invoked[0].data == b"b"


@pytest.mark.asyncio
async def test_click_requires_password_not_invoked() -> None:
    """requires_password 按钮:返回 unsupported,不触发 invoke。"""
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("敏感", callback_data=b"p", requires_password=True)]])
    raw = FakeRaw(
        types.SimpleNamespace(reply_markup=markup, raw=types.SimpleNamespace(rich_message=None), edit_date=None)
    )
    out = await _client(raw).click_inline_button(1, 42, data="p")
    assert out["type"] == "unsupported" and out["button_type"] == ["requires_password"]
    assert out["source"] == "inline"
    assert raw.invoked == []


@pytest.mark.asyncio
async def test_click_no_buttons_raises() -> None:
    raw = FakeRaw(
        types.SimpleNamespace(reply_markup=None, raw=types.SimpleNamespace(rich_message=None), edit_date=None)
    )
    with pytest.raises(McpError) as ei:
        await _client(raw).click_inline_button(1, 42)
    assert ei.value.code == "NO_BUTTONS"


@pytest.mark.asyncio
async def test_click_inline_data_regression() -> None:
    """回归:普通 InlineKeyboardMarkup 按 data 匹配仍走点击路径。"""
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("点我", callback_data=b"btn_1")]])
    raw = FakeRaw(
        types.SimpleNamespace(reply_markup=markup, raw=types.SimpleNamespace(rich_message=None), edit_date=None)
    )
    out = await _client(raw).click_inline_button(1, 42, data="btn_1")
    assert out["type"] == "callback" and out["source"] == "inline"
    assert raw.invoked[0].data == b"btn_1"
