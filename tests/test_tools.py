"""工具层守卫与错误包装测试。"""

from __future__ import annotations

import pytest

from kurigram_mcp.errors import FLOOD_WAIT, McpError
from kurigram_mcp.tools.common import require_chat, wrap_errors


class FakeAccess:
    def __init__(self, allowed: set[int]) -> None:
        self._allowed = allowed

    def is_allowed(self, chat_id: int) -> bool:
        return chat_id in self._allowed


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
