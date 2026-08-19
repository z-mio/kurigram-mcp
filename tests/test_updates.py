"""事件总线与谓词测试。"""

from __future__ import annotations

import asyncio
import time

import pytest

from kurigram_mcp.telegram.updates import EventBus
from kurigram_mcp.tools.bot_debug import build_predicate


def _ev(
    bus: EventBus, type_: str = "message", chat_id: int = 1, payload: dict | None = None
) -> None:
    bus.push(type_, chat_id, payload or {})


@pytest.mark.asyncio
async def test_drain_cursor_semantics() -> None:
    bus = EventBus()
    _ev(bus, "message", 1, payload={"text": "hello", "from": {"is_bot": False}})
    _ev(bus, "message", 2, payload={"text": "world", "from": {"is_bot": True}})
    cursor, events = bus.drain(None)
    assert cursor == 2 and len(events) == 2
    assert [e.seq for e in events] == [1, 2]

    _ev(bus, "edited_message", 1, payload={"text": "hello2"})
    cursor2, events2 = bus.drain(cursor)
    assert cursor2 == 3 and len(events2) == 1 and events2[0].type == "edited_message"

    # 无新事件:cursor 不变
    cursor3, events3 = bus.drain(cursor2)
    assert cursor3 == 3 and events3 == []


@pytest.mark.asyncio
async def test_drain_chat_filter() -> None:
    bus = EventBus()
    _ev(bus, "message", 1, payload={"text": "a"})
    _ev(bus, "message", 2, payload={"text": "b"})
    _, events = bus.drain(None, chat_id=1)
    assert len(events) == 1 and events[0].chat_id == 1


@pytest.mark.asyncio
async def test_wait_matches_and_timeout() -> None:
    bus = EventBus()
    pred = build_predicate(chat_id=1, from_bot=True, text_contains="start")

    task = asyncio.create_task(bus.wait(pred, timeout=5))
    await asyncio.sleep(0.05)
    _ev(bus, "message", 1, payload={"text": "nope", "from": {"is_bot": False}})  # 不匹配
    _ev(bus, "message", 1, payload={"text": "/start 收到", "from": {"is_bot": True}})  # 匹配
    ev = await asyncio.wait_for(task, 2)
    assert ev is not None and ev.payload["text"] == "/start 收到"

    # 超时(用不可能命中的谓词,避免 lookback 命中上一步的事件)
    t0 = time.monotonic()
    ev2 = await bus.wait(build_predicate(chat_id=1, text_contains="绝不存在"), timeout=0.2)
    assert ev2 is None and time.monotonic() - t0 < 2


@pytest.mark.asyncio
async def test_wait_lookback_finds_recent_event() -> None:
    """事件先到、等待后注册:lookback 窗口内应能立即命中。"""
    bus = EventBus()
    _ev(bus, "message", 1, payload={"text": "early reply", "from": {"is_bot": True}})
    pred = build_predicate(chat_id=1, from_bot=True, text_contains="early")
    ev = await bus.wait(pred, timeout=2)  # 不应等待,立即返回
    assert ev is not None and ev.payload["text"] == "early reply"


@pytest.mark.asyncio
async def test_whitelist_filter_drops_events() -> None:
    bus = EventBus()
    bus.set_allowed_ids({1})
    _ev(bus, "message", 1, payload={"text": "allowed"})
    _ev(bus, "message", 2, payload={"text": "dropped"})
    cursor, events = bus.drain(None)
    assert cursor == 1 and len(events) == 1 and events[0].chat_id == 1


def test_predicate_reply_to_and_types() -> None:
    bus = EventBus()
    _ev(
        bus, "message", 1, payload={"text": "x", "from": {"is_bot": True}, "reply_to_message_id": 7}
    )
    ev = bus.drain(None)[1][0]
    p1 = build_predicate(chat_id=1, reply_to_message_id=7)
    p2 = build_predicate(chat_id=1, reply_to_message_id=8)
    p3 = build_predicate(chat_id=1, types=["edited_message"])
    assert p1(ev) and not p2(ev) and not p3(ev)
