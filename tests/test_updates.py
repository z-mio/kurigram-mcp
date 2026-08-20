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
async def test_wait_lookback_covers_agent_round_trip() -> None:
    """回归:bot 同秒回复、agent 数秒后才调用 wait —— 默认 60s 窗口必须命中。

    旧实现 lookback 硬编码 5s,事件年龄 30s 时直接 break → 误报超时。
    """
    bus = EventBus()
    bus.push(
        "message",
        1,
        {"text": "语言代码 xx 无效", "from": {"is_bot": True}, "reply_to_message_id": 11960},
        ts=time.time() - 30,
    )
    ev = await bus.wait(
        build_predicate(chat_id=1, from_bot=True, text_contains="语言代码"), timeout=2
    )
    assert ev is not None and ev.payload["text"] == "语言代码 xx 无效"

    # 显式收窄窗口:事件滑出 → 等满 timeout 后 miss
    ev2 = await bus.wait(
        build_predicate(chat_id=1, from_bot=True, text_contains="语言代码"),
        timeout=0.2,
        lookback_seconds=5,
    )
    assert ev2 is None


@pytest.mark.asyncio
async def test_wait_lookback_scans_non_monotonic_ts() -> None:
    """事件 ts 非单调(旧 ts 事件后入列)也不应漏扫:按年龄过滤全流而非遇旧即断。"""
    bus = EventBus()
    now = time.time()
    bus.push("message", 1, {"text": "newer"}, ts=now)  # 后入列、ts 更新
    bus.push("message", 1, {"text": "old but recent"}, ts=now - 30)  # ts 更旧
    ev = await bus.wait(
        build_predicate(chat_id=1, text_contains="old but recent"),
        timeout=0.2,
        lookback_seconds=60,
    )
    assert ev is not None and ev.payload["text"] == "old but recent"


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


def test_predicate_media_filters() -> None:
    """is_media / media_type 谓词:媒体消息与文本消息应正确区分。"""
    bus = EventBus()
    _ev(bus, "message", 1, payload={"media": "photo", "from": {"is_bot": True}})
    _ev(bus, "message", 1, payload={"text": "纯文本", "from": {"is_bot": True}})
    _ev(bus, "message", 1, payload={"media": "voice", "from": {"is_bot": True}})
    events = bus.drain(None)[1]

    p_photo = build_predicate(chat_id=1, is_media=True)
    p_photo_exact = build_predicate(chat_id=1, media_type="photo")
    p_text = build_predicate(chat_id=1, is_media=False)
    p_voice = build_predicate(chat_id=1, media_type="voice")

    assert p_photo(events[0]) and not p_photo(events[1]) and p_photo(events[2])
    assert p_photo_exact(events[0]) and not p_photo_exact(events[2])
    assert not p_text(events[0]) and p_text(events[1]) and not p_text(events[2])
    assert p_voice(events[2]) and not p_voice(events[0])
    # media_type 匹配时不再要求 chat 内其他谓词
    assert build_predicate(chat_id=2, media_type="photo")(events[0]) is False


def test_predicate_text_matches_regex() -> None:
    """正则谓词:金额/格式断言;非法正则不崩(视为不匹配)。"""
    bus = EventBus()
    _ev(bus, "message", 1, payload={"text": "100.0 USD美元 = 672.5761 CNY人民币", "from": {"is_bot": True}})
    _ev(bus, "message", 1, payload={"text": "没有数字", "from": {"is_bot": True}})
    events = bus.drain(None)[1]
    p_amount = build_predicate(chat_id=1, text_matches=r"\d+\.\d+ CNY")
    assert p_amount(events[0]) and not p_amount(events[1])
    # 非 url/文本之外的事件不崩
    assert build_predicate(chat_id=1, text_matches="(")(events[0]) is False  # 非法正则
    assert build_predicate(chat_id=1, text_matches="USD")(events[0]) is True


@pytest.mark.asyncio
async def test_predicate_after_seq_skips_old_events() -> None:
    """after_seq:连续等待时跳过 lookback 窗口内已返回过的旧事件(子会话实测踩坑场景)。

    场景:第一次 wait 命中旧事件 seq=1;第二次 wait 不传 after_seq 会再次命中,
    传 after_seq=1 则应跳过,等不到时返回 None。
    """
    bus = EventBus()
    bus.push("message", 1, {"text": "旧回复", "from": {"is_bot": True}}, ts=time.time())

    # 不传 after_seq:旧事件被重复命中
    ev1 = await _wait(bus, build_predicate(chat_id=1, from_bot=True, text_contains="旧回复"))
    assert ev1 is not None and ev1.seq == 1
    ev2 = await _wait(bus, build_predicate(chat_id=1, from_bot=True, text_contains="旧回复"))
    assert ev2 is not None and ev2.seq == 1  # 旧事件仍命中(问题场景)

    # 传 after_seq:旧事件被跳过,等待新事件
    bus.push("message", 1, {"text": "新回复", "from": {"is_bot": True}}, ts=time.time())
    ev3 = await _wait(
        bus,
        build_predicate(chat_id=1, from_bot=True, text_contains="新回复", after_seq=1),
    )
    assert ev3 is not None and ev3.seq == 2

    # after_seq 下旧事件不匹配
    p = build_predicate(chat_id=1, from_bot=True, text_contains="旧回复", after_seq=1)
    assert p(ev1) is False


async def _wait(bus, pred, timeout: float = 2):
    return await asyncio.wait_for(bus.wait(pred, timeout=timeout, lookback_seconds=60), 3)
