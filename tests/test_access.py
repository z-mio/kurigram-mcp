"""AccessControl 白名单逻辑测试。"""

from __future__ import annotations

import pytest

from kurigram_mcp.access import AccessControl
from kurigram_mcp.errors import McpError


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeClient:
    def __init__(self, chats: dict[str, int]) -> None:
        self._chats = chats

    async def get_chat(self, name: str) -> FakeChat:
        if name not in self._chats:
            raise ValueError(f"chat not found: {name}")
        return FakeChat(self._chats[name])


@pytest.mark.asyncio
async def test_numeric_ids_and_me() -> None:
    ac = AccessControl("-1001234567890, me", strict=False)
    assert ac.count == 1  # me 尚未解析
    await ac.resolve(FakeClient({}), me_id=777)
    assert ac.is_allowed(-1001234567890)
    assert ac.is_allowed(777)
    assert not ac.is_allowed(1)
    assert not ac.is_allowed(-100999)
    assert ac.count == 2


@pytest.mark.asyncio
async def test_username_with_and_without_at() -> None:
    ac = AccessControl("@mybot, plain_name", strict=False)
    await ac.resolve(FakeClient({"mybot": -1001, "plain_name": 4242}), me_id=0)
    assert ac.is_allowed(-1001)
    assert ac.is_allowed(4242)


@pytest.mark.asyncio
async def test_unresolved_username_skipped_with_warning() -> None:
    ac = AccessControl("@missing", strict=False)
    await ac.resolve(FakeClient({}), me_id=0)
    assert ac.count == 0
    assert not ac.is_allowed(123)


@pytest.mark.asyncio
async def test_strict_mode_raises_on_unresolved() -> None:
    ac = AccessControl("@missing", strict=True)
    with pytest.raises(McpError):
        await ac.resolve(FakeClient({}), me_id=0)


@pytest.mark.asyncio
async def test_empty_whitelist_is_fail_closed() -> None:
    ac = AccessControl("", strict=False)
    await ac.resolve(FakeClient({}), me_id=5)
    assert ac.count == 0
    assert not ac.is_allowed(5)


def test_summary() -> None:
    ac = AccessControl("3, -1, me", strict=False)
    ac._ids.add(2)
    assert ac.summary() == ["-1", "2", "3"]


@pytest.mark.asyncio
async def test_from_header_numeric_and_me() -> None:
    """请求头白名单:数字 + me。"""
    ac = await AccessControl.from_header("-1001, me", FakeClient({}), me_id=777)
    assert ac.is_allowed(-1001)
    assert ac.is_allowed(777)
    assert not ac.is_allowed(1)


@pytest.mark.asyncio
async def test_from_header_username_cached() -> None:
    """请求头白名单:@username 解析并缓存(第二次不重复查询)。"""
    from kurigram_mcp.access import _USERNAME_CACHE

    _USERNAME_CACHE.clear()  # 避免被其他测试的解析结果污染

    class CountingClient(FakeClient):
        calls = 0

        async def get_chat(self, name: str):
            CountingClient.calls += 1
            return await super().get_chat(name)

    CountingClient.calls = 0
    client = CountingClient({"mybot": -100456})
    ac1 = await AccessControl.from_header("@mybot", client, me_id=0)
    ac2 = await AccessControl.from_header("@mybot", client, me_id=0)
    assert ac1.is_allowed(-100456) and ac2.is_allowed(-100456)
    assert CountingClient.calls == 1  # 缓存命中,只查了一次


@pytest.mark.asyncio
async def test_from_header_empty_fail_closed() -> None:
    ac = await AccessControl.from_header("", FakeClient({}), me_id=0)
    assert ac.count == 0
    assert not ac.is_allowed(1)
