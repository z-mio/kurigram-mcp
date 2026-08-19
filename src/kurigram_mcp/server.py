"""MCP 服务器装配与运行。"""

from __future__ import annotations

import hmac
import time
from contextlib import asynccontextmanager

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from . import __version__
from .access import AccessControl
from .config import Settings
from .telegram.client import TelegramClient
from .tools import ServerState, register_tools


class StaticTokenVerifier:
    """比对静态 Bearer token(AUTH_TOKEN 环境变量)。"""

    def __init__(self, expected: str) -> None:
        self._expected = expected

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token, self._expected):
            return AccessToken(token=token, client_id="kurigram-mcp", scopes=[])
        return None


def _auth_settings() -> AuthSettings | None:
    """本地静态 Bearer 鉴权:issuer/resource 填占位 URL,token_verifier 才是真正校验。"""
    return AuthSettings(
        issuer_url="http://127.0.0.1",
        resource_server_url="http://127.0.0.1",
    )


def build_server(settings: Settings) -> MCPServer:
    @asynccontextmanager
    async def lifespan(server: MCPServer):
        client = TelegramClient(settings)
        await client.start()
        access = AccessControl(settings.allowed_chat_ids, settings.strict_whitelist)
        await access.resolve(client.raw, me_id=client.me.id)
        client.bus.set_allowed_ids(access.ids())
        state = ServerState(client=client, access=access, started_at=time.monotonic())
        try:
            yield state
        finally:
            await client.stop()

    kwargs: dict = {"lifespan": lifespan}
    if settings.auth_token:
        kwargs["auth"] = _auth_settings()
        kwargs["token_verifier"] = StaticTokenVerifier(settings.auth_token)

    mcp = MCPServer(
        name="kurigram-mcp",
        title="Kurigram MCP",
        description="MCP server for debugging Telegram bots via a user session (kurigram/pyrogram MTProto)",
        version=__version__,
        **kwargs,
    )
    register_tools(mcp)
    return mcp


def run_server(settings: Settings, **overrides) -> None:
    mcp = build_server(settings)
    mcp.run(
        transport="streamable-http",
        host=overrides.get("host", settings.host),
        port=overrides.get("port", settings.port),
        streamable_http_path=overrides.get("path", "/mcp"),
        stateless_http=bool(overrides.get("stateless", False)),
        json_response=bool(overrides.get("json_response", False)),
    )
