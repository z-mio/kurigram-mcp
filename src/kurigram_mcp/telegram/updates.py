"""事件总线:kurigram handler -> 进程内事件流。

- handler 在客户端事件循环上异步执行,可直接使用 asyncio 原语
- 每个事件分配单调 seq(游标);全局有界流 + 谓词 waiters
- wait 支持 lookback:先查最近事件,避免"事件先到、等待后注册"的竞态
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections import abc, deque
from dataclasses import dataclass

Predicate = abc.Callable[["BusEvent"], bool]


@dataclass
class BusEvent:
    seq: int
    type: str  # message | edited_message | reaction | deleted_message
    chat_id: int
    payload: dict
    ts: float

    @property
    def age_ms(self) -> float:
        return round((time.time() - self.ts) * 1000, 1)


class EventBus:
    """有界事件流 + 广播式 waiters(多个并发等待者都能收到同一事件)。"""

    def __init__(self, maxlen: int = 5000) -> None:
        self._counter = itertools.count(1)
        self._stream: deque[BusEvent] = deque(maxlen=maxlen)
        self._waiters: list[tuple[asyncio.Future[BusEvent], Predicate]] = []
        self._seq = 0
        self._allowed_ids: set[int] | None = None  # None = 不过滤(解析前);设置后白名单过滤

    def set_allowed_ids(self, ids: set[int]) -> None:
        self._allowed_ids = ids

    def push(self, event_type: str, chat_id: int, payload: dict, ts: float | None = None) -> None:
        """推送事件;非白名单 chat 的事件直接丢弃(不占用 seq)。"""
        if self._allowed_ids is not None and chat_id not in self._allowed_ids:
            return
        seq = next(self._counter)
        self._seq = seq
        ev = BusEvent(
            seq=seq, type=event_type, chat_id=chat_id, payload=payload, ts=ts or time.time()
        )
        self._stream.append(ev)
        self._notify_waiters(ev)

    def _notify_waiters(self, ev: BusEvent) -> None:
        for fut, pred in list(self._waiters):
            if fut.done():
                continue
            try:
                ok = pred(ev)
            except Exception:  # noqa: BLE001 - 谓词异常视为不匹配
                ok = False
            if ok:
                fut.set_result(ev)
                self._waiters.remove((fut, pred))

    async def wait(
        self, predicate: Predicate, timeout: float, lookback_seconds: float = 60.0
    ) -> BusEvent | None:
        """等待匹配事件;超时返回 None。lookback 窗口内已有匹配事件则立即返回。

        lookback 必须覆盖"事件先到、wait 后注册"的竞态:bot 常在同一秒内回复,
        而 LLM 客户端从发送消息到发出下一次 wait 调用往往间隔数秒~数十秒,
        故默认 60s(此前 5s 太短,快回复会滑出窗口导致误报"没回复")。
        事件 ts 可能非单调(消息用 message.date、删除/反应用接收时刻),
        因此按年龄过滤全流,遇旧继续向后查找。
        """
        now = time.time()
        for ev in reversed(self._stream):
            if now - ev.ts > lookback_seconds:
                continue
            if predicate(ev):
                return ev

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[BusEvent] = loop.create_future()
        self._waiters.append((fut, predicate))
        try:
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            return None
        finally:
            self._waiters = [(f, p) for (f, p) in self._waiters if f is not fut]

    def drain(
        self, cursor: int | None, chat_id: int | None = None, limit: int = 100
    ) -> tuple[int, list[BusEvent]]:
        """自 cursor 起的事件(可过滤 chat);返回(新 cursor, 事件)。"""
        events = [
            e
            for e in self._stream
            if (cursor is None or e.seq > cursor) and (chat_id is None or e.chat_id == chat_id)
        ]
        if limit and len(events) > limit:
            events = events[-limit:]
        new_cursor = events[-1].seq if events else (self._seq if cursor is None else cursor)
        return new_cursor, events

    @property
    def latest_seq(self) -> int:
        return self._seq


def event_view(ev: BusEvent) -> dict:
    """事件 -> MCP 返回结构。"""
    return {
        "seq": ev.seq,
        "type": ev.type,
        "chat_id": ev.chat_id,
        "age_ms": ev.age_ms,
        "payload": ev.payload,
    }
