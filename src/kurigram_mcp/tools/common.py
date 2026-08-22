"""工具层共享设施:运行时状态、白名单守卫、错误包装。"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..access import AccessControl
from ..errors import ACCOUNT_NOT_FOUND, NOT_WHITELISTED, McpError, to_mcp_error
from ..telegram.client import TelegramClient


@dataclass
class ServerState:
    """lifespan 中构建、工具共享的运行时状态(单服务器多账号)。

    clients/accesses 按账号名索引;default 为缺省账号
    (旧式顶层配置的 "default",或首个成功连接的注册账号)。
    """

    clients: dict[str, TelegramClient] = field(default_factory=dict)
    accesses: dict[str, AccessControl] = field(default_factory=dict)
    default: str = ""
    started_at: float = 0.0

    @property
    def client(self) -> TelegramClient:
        """缺省账号客户端(向后兼容:旧调用不传 account)。"""
        return self.clients[self.default]

    @property
    def access(self) -> AccessControl:
        """缺省账号白名单(向后兼容)。"""
        return self.accesses[self.default]

    def resolve(self, account: str | None) -> TelegramClient:
        """按账号名取客户端;None 用缺省账号。账号未连接时给出明确错误。"""
        if not account:
            return self.client
        client = self.clients.get(account)
        if client is None:
            raise McpError(
                ACCOUNT_NOT_FOUND,
                f"账号 '{account}' 不可用(未注册或未登录);当前已连接: "
                + (", ".join(self.clients) if self.clients else "无"),
            )
        return client

    def resolve_access(self, account: str | None) -> AccessControl:
        if not account:
            return self.access
        access = self.accesses.get(account)
        if access is None:
            raise McpError(
                ACCOUNT_NOT_FOUND,
                f"账号 '{account}' 不可用(未注册或未登录);当前已连接: "
                + (", ".join(self.accesses) if self.accesses else "无"),
            )
        return access


def access_for(state: ServerState, account: str | None = None) -> AccessControl:
    """取账号白名单:账号级 sessions.<name>.allowed_chat_ids,未配置时回退全局。"""
    return state.resolve_access(account)


def require_chat(access, chat_id: int) -> None:
    """白名单守卫:fail-closed,白名单外的 chat_id 一律拒绝。"""
    if not access.is_allowed(chat_id):
        raise McpError(
            NOT_WHITELISTED,
            f"chat_id={chat_id} 不在白名单中(fail-closed),已拒绝;"
            "请通过账号白名单(`km session add NAME --allowed-chat-ids ...`)"
            "或全局配置 ALLOWED_CHAT_IDS 加入",
        )


async def resolve_chat_id(client, chat_id: int | str) -> int:
    """工具参数 chat_id 统一解析为数字 id。

    支持:数字 id(含群/频道负 ID)、@username(带缓存)、me/self(Saved Messages)。
    解析失败(未知用户名等)按 Telegram 原始错误透传。
    """
    if isinstance(chat_id, int):
        return chat_id
    s = str(chat_id).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    from ..access import resolve_username

    return await resolve_username(client.raw, s, client.me.id)


def wrap_errors[F: Callable[..., Awaitable[Any]]](fn: F) -> F:
    """把工具抛出的异常统一转成结构化 ToolError。"""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except McpError as exc:
            raise exc.to_tool_error() from exc
        except Exception as exc:
            raise to_mcp_error(exc).to_tool_error() from exc

    return wrapper  # type: ignore[return-value]
