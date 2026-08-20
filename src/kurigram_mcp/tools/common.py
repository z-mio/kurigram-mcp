"""工具层共享设施:运行时状态、白名单守卫、错误包装。"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..access import AccessControl
from ..errors import NOT_WHITELISTED, McpError, to_mcp_error
from ..telegram.client import TelegramClient


@dataclass
class ServerState:
    """lifespan 中构建、工具共享的运行时状态。"""

    client: TelegramClient
    access: AccessControl
    started_at: float

    @property
    def bus(self):
        """事件总线(client 所有)。"""
        return self.client.bus


ALLOWED_CHATS_HEADER = "x-kurigram-allowed-chats"


async def access_for(ctx, state: ServerState):
    """per-request 白名单:请求头 X-Kurigram-Allowed-Chats 优先,否则用基础配置。

    纯请求头模式:客户端在每个请求头里声明自己的白名单(逗号分隔的数字 id /
    @username / me);未提供时回退服务器配置,保持向后兼容。
    """
    request = getattr(ctx.request_context, "request", None)
    header = request.headers.get(ALLOWED_CHATS_HEADER) if request is not None else None
    if header:
        from ..access import AccessControl

        return await AccessControl.from_header(header, state.client.raw, state.client.me.id)
    return state.access


def require_chat(access, chat_id: int) -> None:
    """白名单守卫:fail-closed,不泄露存在性。"""
    if not access.is_allowed(chat_id):
        raise McpError(
            NOT_WHITELISTED,
            f"chat_id={chat_id} 不在白名单中(fail-closed),已拒绝;"
            "请通过请求头 X-Kurigram-Allowed-Chats 或服务器配置 ALLOWED_CHAT_IDS 加入",
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
