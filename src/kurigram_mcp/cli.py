"""命令行入口:kurigram-mcp [run|auth]。"""

from __future__ import annotations

import argparse
import asyncio
import sys

from loguru import logger

from . import __version__
from .auth import run_auth
from .config import Settings
from .errors import McpError
from .server import run_server
from .setup import run_setup


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), backtrace=False, diagnose=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kurigram-mcp",
        description="MCP server for debugging Telegram bots via a user session",
    )
    parser.add_argument("--version", action="version", version=f"kurigram-mcp {__version__}")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="启动 MCP 服务器(默认命令)")
    run_p.add_argument("--host", help="监听地址(默认取 HOST,127.0.0.1)")
    run_p.add_argument("--port", type=int, help="监听端口(默认取 PORT,8765)")
    run_p.add_argument("--path", default="/mcp", help="Streamable HTTP 端点路径(默认 /mcp)")
    run_p.add_argument(
        "--stateful", action="store_true", help="使用有状态会话模式(默认无状态,推荐)"
    )
    run_p.add_argument(
        "--json-response", action="store_true", help="纯 JSON 响应,不用 SSE(部分客户端不支持)"
    )

    sub.add_parser("auth", help="交互式登录 Telegram(需先配置 API_ID/API_HASH)")

    sub.add_parser("setup", help="交互式配置向导:生成 ~/.kurigram-mcp/config")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level)

    if args.command == "setup":
        return run_setup()

    if args.command == "auth":
        try:
            return asyncio.run(run_auth(settings))
        except McpError as exc:
            logger.error(exc.message)
            return 1

    # 默认:run
    overrides = {}
    if args.host:
        overrides["host"] = args.host
    if args.port:
        overrides["port"] = args.port
    if args.path:
        overrides["path"] = args.path
    overrides["stateless"] = not args.stateful  # 默认无状态(服务器重启客户端自动恢复)
    if args.json_response:
        overrides["json_response"] = True

    logger.info("kurigram-mcp v{} 启动中 (transport=streamable-http)", __version__)
    run_server(settings, **overrides)
    return 0
