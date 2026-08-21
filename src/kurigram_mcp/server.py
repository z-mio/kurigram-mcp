"""MCP 服务器装配与运行。"""

from __future__ import annotations

import hmac
import time
from contextlib import asynccontextmanager

from loguru import logger
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from . import __version__
from .access import AccessControl
from .config import Settings
from .errors import ACCOUNT_NOT_FOUND, McpError
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


def build_server(settings: Settings, accounts: list[str] | None = None) -> MCPServer:
    """accounts 为 None 时启动全部已注册账号;否则只启动指定账号列表。"""

    @asynccontextmanager
    async def lifespan(server: MCPServer):
        names = settings.account_names() if accounts is None else accounts
        clients: dict[str, TelegramClient] = {}
        accesses: dict[str, AccessControl] = {}
        for name in names:
            acc_settings = settings.resolve_account(name)
            client = TelegramClient(acc_settings)
            try:
                await client.start()
            except McpError as exc:
                logger.warning("账号 '{}' 启动失败,跳过: {}", name, exc.message)
                continue
            access = AccessControl(acc_settings.allowed_chat_ids, acc_settings.strict_usernames)
            await access.resolve(client.raw, me_id=client.me.id)
            client.bus.set_allowed_ids(access.ids())
            me = client.me
            dc = getattr(getattr(client.raw, "session", None), "dc_id", None)
            _refresh_me_snapshot(acc_settings, me, dc)
            logger.info(
                "账号 '{}' (api_id={}) 已连接: {} @{}",
                name,
                acc_settings.api_id,
                getattr(me, "first_name", "?"),
                getattr(me, "username", None) or getattr(me, "id", "?"),
            )
            clients[name] = client
            accesses[name] = access
        if not clients:
            raise McpError(
                ACCOUNT_NOT_FOUND,
                "没有可用的已登录账号;请先运行 `kurigram-mcp session add <name>` 完成登录",
            )
        default = names[0] if names[0] in clients else next(iter(clients))
        state = ServerState(clients=clients, accesses=accesses, default=default, started_at=time.monotonic())
        try:
            yield state
        finally:
            for client in clients.values():
                try:
                    await client.stop()
                except Exception as exc:  # noqa: BLE001 - 停止失败不影响退出
                    logger.debug("关闭账号客户端时出错: {}", exc)

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


def _refresh_me_snapshot(acc_settings: Settings, me, dc: int | None) -> None:
    """启动成功后刷新注册表中的身份快照(让 `session list` 离线展示保持新鲜)。"""
    try:
        from .sessions import make_me_snapshot, update_me

        update_me(
            acc_settings,
            make_me_snapshot(
                first_name=getattr(me, "first_name", "") or "",
                username=getattr(me, "username", None),
                dc=dc,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - 快照刷新失败不影响启动
        logger.debug("刷新身份快照失败: {}", exc)


def run_server(settings: Settings, accounts: list[str] | None = None, **overrides) -> None:
    mcp = build_server(settings, accounts)
    mcp.run(
        transport="streamable-http",
        host=overrides.get("host", settings.host),
        port=overrides.get("port", settings.port),
        streamable_http_path=overrides.get("path", "/mcp"),
        stateless_http=bool(overrides.get("stateless", False)),
        json_response=bool(overrides.get("json_response", False)),
    )
