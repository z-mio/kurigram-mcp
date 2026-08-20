"""聊天白名单访问控制:默认 fail-closed,不在白名单内的 chat 一律拒绝。

白名单来源(按账号解析):
1. 账号级白名单 sessions.<name>.allowed_chat_ids(每账号独立,本次新增)
2. 全局配置 ALLOWED_CHAT_IDS(账号级未配置时的兜底)
条目支持:数字 chat_id(含负 ID)、@username、me(Saved Messages)。
"""

from __future__ import annotations

import time

from loguru import logger

from .errors import INTERNAL, McpError

# username → (chat_id, 解析时间),TTL 内复用,避免每请求网络调用
_USERNAME_CACHE: dict[str, tuple[int, float]] = {}
_USERNAME_TTL = 60.0


async def resolve_username(client, name: str, me_id: int) -> int:
    """解析 @username / me -> 数字 chat_id(TTL 缓存;client 需提供 async get_chat)。

    供白名单与工具层 chat_id 参数共用,保证同一用户名在同一窗口期解析一致。
    """
    key = name.strip().removeprefix("@").lower()
    if key in ("me", "self"):
        return me_id
    now = time.time()
    cached = _USERNAME_CACHE.get(key)
    if cached and now - cached[1] < _USERNAME_TTL:
        return cached[0]
    chat = await client.get_chat(key)
    _USERNAME_CACHE[key] = (chat.id, now)
    return chat.id


class AccessControl:
    def __init__(self, raw: str = "", strict: bool = False) -> None:
        self.strict = strict
        self._ids: set[int] = set()
        self._usernames: set[str] = set()
        self._want_me = False
        self._unresolved: list[str] = []

        for entry in (e.strip() for e in raw.split(",") if e.strip()):
            if entry == "me":
                self._want_me = True
            elif entry.lstrip("-").isdigit():
                self._ids.add(int(entry))
            else:
                self._usernames.add(entry.removeprefix("@"))

    async def resolve(self, client, me_id: int) -> None:
        """解析 me 与 @username;client 需提供 async get_chat(name)。"""
        if self._want_me:
            self._ids.add(me_id)
        for name in sorted(self._usernames):
            try:
                self._ids.add(await resolve_username(client, name, me_id))
            except Exception as exc:  # noqa: BLE001 - 解析失败按条目处理
                self._unresolved.append(name)
                logger.warning("白名单条目解析失败 @{}: {}", name, exc)
        if self.strict and self._unresolved:
            raise McpError(
                INTERNAL,
                f"STRICT_WHITELIST 下解析失败: {', '.join('@' + n for n in self._unresolved)}",
            )

    def is_allowed(self, chat_id: int) -> bool:
        return chat_id in self._ids

    def ids(self) -> set[int]:
        """已解析的白名单 chat id 集合。"""
        return set(self._ids)

    def summary(self) -> list[str]:
        return sorted(str(i) for i in self._ids)

    @property
    def count(self) -> int:
        return len(self._ids)
