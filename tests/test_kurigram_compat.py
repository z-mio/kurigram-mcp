"""kurigram 2.2.26 API 兼容性回归测试。

覆盖 2.2.26 带来的三类破坏性变更(违反其中任何一条都会静默降级或启动失败):
1. proxy 只接受冻结 dataclass,裸 dict 不再是客户端接受的形态;
2. reply_to_message_id / get_chat_history(offset_id=) 等平铺参数已弃用;
3. MessageReactionUpdated.new_reaction 是列表,按单对象读取会永远得到 None。
"""

from __future__ import annotations

import types

import pytest
from pyrogram import Client
from pyrogram.connection import HTTPProxy, SOCKS4Proxy, SOCKS5Proxy

from kurigram_mcp.telegram.client import TelegramClient, _reply, parse_proxy


def _fake_message(**overrides):
    """message_view 能消化的最小消息替身。"""
    base = {
        "id": 42,
        "chat": types.SimpleNamespace(id=6540476263),
        "date": None,
        "edit_date": None,
        "out": True,
        "from_user": None,
        "text": "hi",
        "caption": None,
        "media": None,
        "media_group_id": None,
        "poll": None,
        "reply_to_message_id": None,
        "service": None,
        "reply_markup": None,
        "raw": None,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


class RecordingRaw:
    """记录 kurigram 调用实参的假 Client(只实现被测方法)。"""

    def __init__(self, message=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._message = message or _fake_message()
        self.handlers: list = []

    def _record(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        return self._message

    async def send_message(self, chat_id, text, **kw):
        return self._record("send_message", **kw)

    async def send_photo(self, chat_id, media, **kw):
        return self._record("send_photo", **kw)

    async def send_document(self, chat_id, media, **kw):
        return self._record("send_document", **kw)

    async def send_voice(self, chat_id, media, **kw):
        return self._record("send_voice", **kw)

    async def send_sticker(self, chat_id, media, **kw):
        return self._record("send_sticker", **kw)

    async def send_media_group(self, chat_id, media, **kw):
        self.calls.append(("send_media_group", kw))
        return [self._message]

    def get_chat_history(self, chat_id, **kw):
        self.calls.append(("get_chat_history", kw))

        async def gen():
            for _ in range(2):
                yield _fake_message()

        return gen()

    def add_handler(self, handler) -> None:
        self.handlers.append(handler)


def _client(raw: RecordingRaw) -> TelegramClient:
    tc = TelegramClient.__new__(TelegramClient)
    tc._client = raw
    return tc


# ---------- 1. proxy:冻结 dataclass ----------


@pytest.mark.parametrize(
    ("url", "cls", "expected"),
    [
        ("socks5://u:p@1.2.3.4:1080", SOCKS5Proxy, ("1.2.3.4", 1080, "u", "p")),
        ("socks4://1.2.3.4:1081", SOCKS4Proxy, ("1.2.3.4", 1081, None, None)),
        ("http://1.2.3.4:8080", HTTPProxy, ("1.2.3.4", 8080, None, None)),
    ],
)
def test_parse_proxy_returns_typed_proxy(url, cls, expected) -> None:
    obj = parse_proxy(url)
    assert isinstance(obj, cls)
    assert (obj.hostname, obj.port, obj.username, obj.password) == expected
    # 关键:2.2.26 的 Client 必须接受该对象(裸 dict 曾导致类型不匹配)
    assert isinstance(Client("probe", api_id=1, api_hash="h", proxy=obj).proxy, cls)


def test_parse_proxy_none_and_unknown_scheme() -> None:
    assert parse_proxy(None) is None
    with pytest.raises(Exception, match="不支持的代理协议"):
        parse_proxy("mtproxy://1.2.3.4:443")


# ---------- 2. 弃用参数 ----------


def test_reply_builds_reply_parameters() -> None:
    assert _reply(None) is None
    params = _reply(77)
    assert params is not None and params.message_id == 77


@pytest.mark.asyncio
async def test_send_methods_use_reply_parameters_not_deprecated_kwarg() -> None:
    """6 个发送方法都必须走 reply_parameters,不能再传已弃用的 reply_to_message_id。"""
    raw = RecordingRaw()
    tc = _client(raw)

    await tc.send_message(1, "x", reply_to_message_id=5)
    await tc.send_photo(1, "p.jpg", reply_to_message_id=5)
    await tc.send_document(1, "d.bin", reply_to_message_id=5)
    await tc.send_voice(1, "v.ogg", reply_to_message_id=5)
    await tc.send_sticker(1, "s.webp", reply_to_message_id=5)
    await tc.send_media_group(1, ["p.jpg"], reply_to_message_id=5)

    assert [name for name, _ in raw.calls] == [
        "send_message",
        "send_photo",
        "send_document",
        "send_voice",
        "send_sticker",
        "send_media_group",
    ]
    for name, kwargs in raw.calls:
        assert "reply_to_message_id" not in kwargs, name
        params = kwargs["reply_parameters"]
        assert params is not None and params.message_id == 5, name


@pytest.mark.asyncio
async def test_send_without_reply_passes_none() -> None:
    raw = RecordingRaw()
    await _client(raw).send_message(1, "x")
    assert raw.calls[0][1]["reply_parameters"] is None


@pytest.mark.asyncio
async def test_get_chat_history_uses_max_id_not_deprecated_offset_id() -> None:
    """offset_id 在 2.2.26 会被静默忽略(永远返回最新一页),必须改用 max_id。"""
    raw = RecordingRaw()
    tc = _client(raw)

    await tc.get_chat_history(1, limit=2, offset_id=None)
    await tc.get_chat_history(1, limit=2, offset_id=51)

    (_, first), (_, second) = raw.calls
    assert first == {"limit": 2, "max_id": 0}  # 首页:max_id=0 即"未提供"
    assert second == {"limit": 2, "max_id": 50}  # 游标 51 -> 只取比 51 更旧的
    for _, kwargs in raw.calls:
        assert "offset_id" not in kwargs


@pytest.mark.asyncio
async def test_get_chat_history_cursor_at_oldest_returns_empty_page() -> None:
    """消息 id 从 1 开始:游标已到 1 时不应再请求 kurigram(否则 max_id=0 会重放最新页)。"""
    raw = RecordingRaw()
    out = await _client(raw).get_chat_history(1, limit=2, offset_id=1)
    assert raw.calls == []
    assert out == {"chat_id": 1, "count": 0, "next_offset_id": None, "messages": []}


# ---------- 3. reaction 载荷 ----------


@pytest.mark.asyncio
async def test_reaction_handler_reads_emoji_from_reaction_list() -> None:
    """new_reaction 是列表;按单对象读取 emoji 会永远得到 None(曾被静默丢字段)。"""
    raw = RecordingRaw()
    tc = _client(raw)
    tc.bus = _RecordingBus()

    tc._register_update_handlers()
    from pyrogram.handlers import MessageReactionHandler

    handler = next(h for h in raw.handlers if isinstance(h, MessageReactionHandler))
    reaction = types.SimpleNamespace(
        chat=types.SimpleNamespace(id=99),
        message_id=7,
        user=types.SimpleNamespace(id=5, username="bob", is_bot=False),
        date=None,
        new_reaction=[
            types.SimpleNamespace(emoji=None, custom_emoji_id="555"),
            types.SimpleNamespace(emoji="👍", custom_emoji_id=None),
        ],
    )
    await handler.callback(None, reaction)

    assert len(tc.bus.pushed) == 1
    chat_id, payload = tc.bus.pushed[0]
    assert chat_id == 99
    assert payload["emoji"] == "👍"
    assert payload["custom_emoji_id"] == "555"
    assert payload["emojis"] == ["👍"]
    assert payload["custom_emoji_ids"] == ["555"]
    assert payload["message_id"] == 7
    assert payload["user"] == {"id": 5, "username": "bob", "is_bot": False}


class _RecordingBus:
    def __init__(self) -> None:
        self.pushed: list[tuple[int, dict]] = []

    def push(self, event_type: str, chat_id: int, payload: dict, ts: float | None = None) -> None:
        self.pushed.append((chat_id, payload))

    def set_allowed_ids(self, ids) -> None:  # pragma: no cover - 协议占位
        pass
