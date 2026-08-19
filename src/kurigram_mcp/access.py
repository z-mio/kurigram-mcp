"""聊天白名单访问控制:默认 fail-closed,不在白名单内的 chat 一律拒绝。

白名单来源(优先级):
1. 请求头 X-Kurigram-Allowed-Chats(HTTP 模式,per-client 声明,纯请求头模式)
2. 服务器基础配置 ALLOWED_CHAT_IDS(兜底)
条目支持:数字 chat_id(含负 ID)、@username、me(Saved Messages)。
"""

from __future__ import annotations

import time

from loguru import logger

from .errors import INTERNAL, McpError

# username → (chat_id, 解析时间),TTL 内复用,避免每请求网络调用
_USERNAME_CACHE: dict[str, tuple[int, float]] = {}
_USERNAME_TTL = 60.0


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
            cached = _USERNAME_CACHE.get(name)
            now = time.time()
            if cached and now - cached[1] < _USERNAME_TTL:
                self._ids.add(cached[0])
                continue
            try:
                chat = await client.get_chat(name)
                self._ids.add(chat.id)
                _USERNAME_CACHE[name] = (chat.id, now)
            except Exception as exc:  # noqa: BLE001 - 解析失败按条目处理
                self._unresolved.append(name)
                logger.warning("白名单条目解析失败 @{}: {}", name, exc)
        if self.strict and self._unresolved:
            raise McpError(
                INTERNAL,
                f"STRICT_WHITELIST 下解析失败: {', '.join('@' + n for n in self._unresolved)}",
            )

    @classmethod
    async def from_header(cls, header_value: str, client, me_id: int) -> AccessControl:
        """从请求头构建白名单(me/@username 即时解析,username 带缓存)。"""
        ac = cls(header_value, strict=False)
        await ac.resolve(client, me_id)
        return ac

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
