"""工具层守卫与错误包装测试。"""

from __future__ import annotations

import types

import pytest

from kurigram_mcp.errors import FLOOD_WAIT, McpError
from kurigram_mcp.tools.common import require_chat, resolve_chat_id, wrap_errors


class FakeAccess:
    def __init__(self, allowed: set[int]) -> None:
        self._allowed = allowed

    def is_allowed(self, chat_id: int) -> bool:
        return chat_id in self._allowed


class FakeRaw:
    """伪 pyrogram Client:get_chat 支持 username 解析。"""

    def __init__(self, users: dict[str, int]) -> None:
        self.users = users
        self.calls = 0

    async def get_chat(self, name: str):
        self.calls += 1
        if name not in self.users:
            raise ValueError(f"username not found: {name}")
        return types.SimpleNamespace(id=self.users[name])


class FakeClient:
    def __init__(self, users: dict[str, int]) -> None:
        self.raw = FakeRaw(users)
        self.me = types.SimpleNamespace(id=99)


@pytest.mark.asyncio
async def test_resolve_chat_id_forms() -> None:
    client = FakeClient({"ziotestbot": 6540476263, "glbetabot": 8977177737})
    assert await resolve_chat_id(client, 5) == 5
    assert await resolve_chat_id(client, -1001973476176) == -1001973476176
    assert await resolve_chat_id(client, "-1001973476176") == -1001973476176
    assert await resolve_chat_id(client, "@ziotestbot") == 6540476263
    assert await resolve_chat_id(client, "ziotestbot") == 6540476263
    assert await resolve_chat_id(client, "me") == 99
    assert await resolve_chat_id(client, "Me") == 99
    assert await resolve_chat_id(client, "@GLBetabot") == 8977177737


@pytest.mark.asyncio
async def test_resolve_chat_id_username_cache() -> None:
    """同用户名二次解析应命中 TTL 缓存,不再发起网络调用。"""
    from kurigram_mcp import access as access_mod

    access_mod._USERNAME_CACHE.clear()
    try:
        client = FakeClient({"ziotestbot": 1})
        assert await resolve_chat_id(client, "@ziotestbot") == 1
        assert await resolve_chat_id(client, "@ziotestbot") == 1
        assert client.raw.calls == 1
    finally:
        access_mod._USERNAME_CACHE.clear()


@pytest.mark.asyncio
async def test_resolve_chat_id_unknown_username_raises() -> None:
    client = FakeClient({})
    with pytest.raises(ValueError):
        await resolve_chat_id(client, "@nobody")


def test_require_chat_allows_whitelisted() -> None:
    access = FakeAccess({5, 6540476263})
    require_chat(access, 5)  # 不应抛错
    require_chat(access, 6540476263)


def test_require_chat_fail_closed() -> None:
    access = FakeAccess({5})
    with pytest.raises(McpError) as ei:
        require_chat(access, 6)
    assert ei.value.code == "NOT_WHITELISTED"
    assert "6540476263" not in str(ei.value)  # 不泄露其他 id 信息


@pytest.mark.asyncio
async def test_wrap_errors_preserves_mcp_error() -> None:
    @wrap_errors
    async def boom() -> None:
        raise McpError(FLOOD_WAIT, "wait 5s", {"seconds": 5})

    with pytest.raises(Exception) as ei:
        await boom()
    assert "[FLOOD_WAIT]" in str(ei.value)


@pytest.mark.asyncio
async def test_wrap_errors_maps_unknown() -> None:
    @wrap_errors
    async def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(Exception) as ei:
        await boom()
    assert "[INTERNAL]" in str(ei.value)


@pytest.mark.asyncio
async def test_wrap_errors_passthrough_result() -> None:
    @wrap_errors
    async def ok() -> dict:
        return {"fine": True}

    assert await ok() == {"fine": True}


def test_auth_settings_constructible() -> None:
    """AuthSettings 必填字段(issuer/resource)都能构造——防止 SDK 字段变化导致启动崩溃。"""
    from kurigram_mcp.server import _auth_settings

    auth = _auth_settings()
    assert auth is not None
    assert str(auth.issuer_url) == "http://127.0.0.1"
    assert str(auth.resource_server_url) == "http://127.0.0.1"
