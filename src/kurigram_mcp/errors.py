"""结构化业务错误:带稳定 code,供 AI 客户端识别与处置。"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

# 错误码(稳定契约,工具文档引用)
NOT_WHITELISTED = "NOT_WHITELISTED"
CHAT_NOT_FOUND = "CHAT_NOT_FOUND"
FLOOD_WAIT = "FLOOD_WAIT"
SESSION_INVALID = "SESSION_INVALID"
NETWORK = "NETWORK"
RPC = "RPC"
INTERNAL = "INTERNAL"


class McpError(Exception):
    """结构化业务错误。"""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_tool_error(self) -> ToolError:
        return ToolError(f"[{self.code}] {self.message}")


def to_mcp_error(exc: Exception) -> McpError:
    """把 kurigram/pyrogram 与连接层异常映射为结构化错误。"""
    import re

    from pyrogram.errors import FloodWait, RPCError, Unauthorized

    if isinstance(exc, FloodWait):
        seconds: int | None = None
        m = re.search(r"(\d+)", str(getattr(exc, "value", "")))
        if m:
            seconds = int(m.group(1))
        wait = f"建议等待 {seconds}s" if seconds is not None else "请稍后重试"
        return McpError(FLOOD_WAIT, f"触发 Telegram 频率限制,{wait}", {"seconds": seconds})
    if isinstance(exc, Unauthorized):
        return McpError(
            SESSION_INVALID,
            "Telegram 会话已失效(登录状态过期),请重新运行 `kurigram-mcp auth`",
            {"rpc_name": getattr(exc, "x", None)},
        )
    if isinstance(exc, RPCError):
        return McpError(
            RPC,
            f"Telegram RPC 错误: {exc}",
            {"rpc_name": getattr(exc, "x", None)},
        )
    if isinstance(exc, (OSError, ConnectionError)):
        return McpError(NETWORK, f"网络/连接错误: {exc}")
    return McpError(INTERNAL, f"{type(exc).__name__}: {exc}")
