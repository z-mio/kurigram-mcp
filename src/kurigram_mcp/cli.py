"""命令行入口:kurigram-mcp [run|auth|session|setup]。"""

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

try:
    from . import sessions as session_store
except ImportError:  # pragma: no cover - 仅防御
    session_store = None


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
    run_p.add_argument("--account", help="使用指定账号(见 `session list`;默认 default 或首个注册账号)")
    run_p.add_argument("--host", help="监听地址(默认取 HOST,127.0.0.1)")
    run_p.add_argument("--port", type=int, help="监听端口(默认取 PORT,8765)")
    run_p.add_argument("--path", default="/mcp", help="Streamable HTTP 端点路径(默认 /mcp)")
    run_p.add_argument(
        "--stateful", action="store_true", help="使用有状态会话模式(默认无状态,推荐)"
    )
    run_p.add_argument(
        "--json-response", action="store_true", help="纯 JSON 响应,不用 SSE(部分客户端不支持)"
    )

    auth_p = sub.add_parser("auth", help="交互式登录 Telegram(需先配置 API_ID/API_HASH)")
    auth_p.add_argument("name", nargs="?", help="账号名(缺省时:单账号直接使用,多账号交互选择)")

    session_p = sub.add_parser("session", help="会话(账号)管理:add / list / remove")
    session_sub = session_p.add_subparsers(dest="session_command")

    add_p = session_sub.add_parser("add", help="注册新账号(凭据写入 config.yaml,尚未登录)")
    add_p.add_argument("name", help="账号名(2-32 位字母/数字/_/-)")
    add_p.add_argument("--api-id", type=int, required=True, help="API_ID(my.telegram.org/apps)")
    add_p.add_argument("--api-hash", required=True, help="API_HASH")
    add_p.add_argument("--proxy", help="该账号专用代理(可选,如 socks5://127.0.0.1:1080)")
    add_p.add_argument("--allowed-chat-ids", help="该账号专用白名单(可选,逗号分隔;留空用全局)")

    list_p = session_sub.add_parser("list", aliases=["ls"], help="列出所有账号与登录状态")
    list_p.add_argument("-v", "--verbose", action="store_true", help="显示 proxy/白名单等完整信息")

    rm_p = session_sub.add_parser("remove", aliases=["rm"], help="删除账号(注册条目 + 会话文件)")
    rm_p.add_argument("name", help="账号名(或保留名 default)")
    rm_p.add_argument("-f", "--force", action="store_true", help="跳过确认(非交互环境必需)")

    sub.add_parser("setup", help="交互式配置向导:生成 ~/.kurigram-mcp/config")
    return parser


def _resolve(settings: Settings, name: str | None) -> Settings:
    """解析账号;多账号且未指定时交互选择。"""
    names = settings.account_names()
    if name:
        return settings.resolve_account(name)
    if len(names) == 1:
        return settings.resolve_account(names[0])
    if not names:
        raise McpError(
            "ACCOUNT_NOT_FOUND",
            "未配置任何账号;运行 `kurigram-mcp setup` 或 `kurigram-mcp session add`",
        )
    print("可用账号:")
    for i, n in enumerate(names, 1):
        print(f"  [{i}] {n}")
    choice = input(f"选择账号(1-{len(names)}): ").strip()
    try:
        idx = int(choice)
        if not 1 <= idx <= len(names):
            raise ValueError
    except ValueError:
        raise McpError("ACCOUNT_NOT_FOUND", f"无效选择: {choice!r}") from None
    return settings.resolve_account(names[idx - 1])


def _cmd_session(settings: Settings, args: argparse.Namespace) -> int:
    if session_store is None:  # pragma: no cover
        logger.error("sessions 模块不可用")
        return 1
    cmd = args.session_command or "list"

    if cmd == "add":
        try:
            result = session_store.add_session(
                settings,
                args.name,
                args.api_id,
                args.api_hash,
                proxy=args.proxy,
                allowed_chat_ids=args.allowed_chat_ids or "",
            )
        except McpError as exc:
            logger.error(exc.message)
            return 1
        logger.success(
            "账号 '{}' 已注册(api_id={});会话文件 {};请运行 `kurigram-mcp auth {}` 登录",
            result["name"],
            result["api_id"],
            result["session_file"],
            result["name"],
        )
        return 0

    if cmd == "remove":
        try:
            result = session_store.remove_session(settings, args.name, force=args.force)
        except McpError as exc:
            logger.error(exc.message)
            return 1
        logger.success(
            "账号 '{}' 已删除(会话文件{} {})",
            result["name"],
            "已删除" if result["deleted_file"] else "不存在",
            result["session_file"],
        )
        return 0

    # list
    rows = session_store.list_sessions(settings)
    if not rows:
        logger.warning("未配置任何账号;运行 `kurigram-mcp setup` 或 `kurigram-mcp session add`")
        return 0
    header = f"{'账号':<12} {'API_ID':<12} {'登录状态':<32} 会话文件"
    print(header)
    print("-" * len(header))
    for r in rows:
        me = r["me"] or {}
        if r["logged_in"]:
            who = me.get("username")
            identity = f"{me.get('first_name', '?')} (@{who})" if who else me.get("first_name", "?")
            status = f"✓ {identity} dc={me.get('dc', '?')} {me.get('last_login', '')}"
        else:
            status = "✗ 未登录(运行 km auth {})".format(r["name"])
        extras = ""
        if args.verbose:
            extras = f" proxy={r['proxy'] or '-'} whitelist={r['allowed_chat_ids'] or '(全局)'}"
        print(f"{r['name']:<12} {r['api_id']:<12} {status:<32} {r['session_file']}{extras}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level)

    if args.command == "setup":
        return run_setup()

    if args.command == "session":
        return _cmd_session(settings, args)

    if args.command == "auth":
        try:
            account = _resolve(settings, args.name)
            logger.info("登录账号: {} (api_id={})", account.account_name, account.api_id)
            return asyncio.run(run_auth(account))
        except McpError as exc:
            logger.error(exc.message)
            return 1

    # 默认:run(裸 kurigram-mcp 也按 run 处理)
    overrides = {}
    if getattr(args, "host", None):
        overrides["host"] = args.host
    if getattr(args, "port", None):
        overrides["port"] = args.port
    if getattr(args, "path", None):
        overrides["path"] = args.path
    overrides["stateless"] = not getattr(args, "stateful", False)  # 默认无状态(服务器重启客户端自动恢复)
    if getattr(args, "json_response", False):
        overrides["json_response"] = True

    try:
        account = settings.resolve_account(getattr(args, "account", None))
    except McpError as exc:
        logger.error(exc.message)
        return 1
    if not account.session_file.exists():
        logger.error(
            "账号 '{}' 未登录:未找到会话文件 {};请先运行 `kurigram-mcp auth {}`",
            account.account_name,
            account.session_file,
            account.account_name,
        )
        return 1

    logger.info(
        "kurigram-mcp v{} 启动中 (账号={} api_id={} transport=streamable-http)",
        __version__,
        account.account_name,
        account.api_id,
    )
    run_server(account, **overrides)
    return 0
