"""命令行入口:kurigram-mcp [run|session|status|restart|setup|auth]。

设计原则:
- 不带参数 = 交互向导(默认值全覆盖,回车即过);
- 带参数 = 脚本模式(行为确定,秘密仍走 getpass/交互);
- `session add` 是唯一入口:注册 + 登录一条命令,不授权 = 不记录。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from loguru import logger

from . import __version__
from .auth import login
from .config import DEFAULT_ACCOUNT, Settings
from .errors import McpError
from .server import run_server
from .serverctl import port_open, restart_server, server_process
from .setup import run_setup

try:
    from . import sessions as session_store
except ImportError:  # pragma: no cover
    session_store = None


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), backtrace=False, diagnose=False)


# ---- 交互组件 ----

def _ask(prompt: str, default: str | None = None, secret: bool = False) -> str:
    """交互输入;空输入返回默认值(secret 走 getpass)。EOF/Ctrl-C 直接退出。"""
    label = f"{prompt} [默认: {default}]" if default else prompt
    try:
        if secret:
            import getpass

            return getpass.getpass(label + ": ").strip()
        return input(label + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(1) from None
    finally:
        # 秘密输入后补一行,避免输出粘连
        if secret:
            print()


def _pick(prompt: str, options: list[tuple[str, str]]) -> int:
    """编号选择器;返回选中下标。options: (显示文本, 描述)。"""
    print(prompt)
    for i, (label, desc) in enumerate(options, 1):
        desc = f" — {desc}" if desc else ""
        print(f"  [{i}] {label}{desc}")
    while True:
        choice = input("> ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(options):
                return idx - 1
        except ValueError:
            pass
        print(f"✗ 无效选择: {choice!r}")


def _confirm(prompt: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{prompt} {suffix}: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("✗ 请输入 y 或 n")


# ---- 表格展示 ----

def _disp_width(s: str) -> int:
    """终端显示宽度:CJK 等宽字符按 2 列计。"""
    return sum(2 if ord(ch) > 0x7F else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    """按终端显示宽度右补空格。"""
    return s + " " * max(0, width - _disp_width(s))


def _print_account_table(rows: list[dict], verbose: bool = False) -> None:
    data_rows = []
    for r in rows:
        me = r["me"] or {}
        if r["logged_in"]:
            who = me.get("username")
            identity = f"{me.get('first_name', '?')} (@{who})" if who else me.get("first_name", "?")
            status = f"✓ {identity} dc={me.get('dc', '?')}"
            if verbose and me.get("last_login"):
                status += f" 登录于 {me['last_login']}"
        else:
            status = "✗ 未登录"
        extras = ""
        if verbose:
            extras = f"  proxy={r['proxy'] or '-'}  whitelist={r['allowed_chat_ids'] or '(全局)'}"
        data_rows.append((r["name"], str(r["api_id"]), status, extras))

    name_w = max([_disp_width("账号")] + [_disp_width(x[0]) for x in data_rows])
    api_w = max([_disp_width("API_ID")] + [_disp_width(x[1]) for x in data_rows])
    st_w = max([_disp_width("登录状态")] + [_disp_width(x[2]) for x in data_rows])
    name_w = max(name_w, 10)
    api_w = max(api_w, 12)
    st_w = max(st_w, 20)
    gap = "  "

    print(f"{_pad('账号', name_w)}{gap}{_pad('API_ID', api_w)}{gap}{_pad('登录状态', st_w)}")
    print("-" * (name_w + api_w + st_w + len(gap) * 2))
    for name, api_id, status, extras in data_rows:
        print(f"{_pad(name, name_w)}{gap}{_pad(api_id, api_w)}{gap}{_pad(status, st_w)}{extras}")


# ---- 会话管理 ----

def _save_me(acc_settings: Settings, result: dict) -> None:
    """登录成功后写回身份快照(失败只告警,不影响结果)。"""
    try:
        from .sessions import make_me_snapshot, update_me

        update_me(
            acc_settings,
            make_me_snapshot(
                first_name=result["me"]["first_name"],
                username=result["me"]["username"],
                dc=result["me"]["dc"],
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("写回身份快照失败: {}", exc)


def _maybe_restart(settings: Settings) -> None:
    """账号/白名单改动后:服务器在跑则问是否重启。"""
    if not sys.stdin.isatty():
        return
    if server_process() is None:
        print("提示: 服务器未运行,`km run` 启动后生效")
        return
    if _confirm("服务器正在运行,是否重启加载变更?", default=True):
        restart_server(settings)
    else:
        print("提示: 稍后 `km restart` 生效")


def _server_online(settings: Settings) -> bool:
    """服务器进程存在且端口在监听(在线 = 账号已连接,会话有效)。"""
    return server_process() is not None and port_open(settings.port)


def _cmd_session_add(settings: Settings, args: argparse.Namespace) -> int:
    name = (args.name or "").strip()
    if not name:
        name = _ask("账号名").strip()
    if not name:
        logger.error("账号名不能为空")
        return 1

    # default 账号 = 顶层配置;命名账号 = 注册表
    if name == DEFAULT_ACCOUNT:
        if not settings.api_id:
            logger.error("账号 'default' 未配置(顶层 API_ID 为空);请先运行 `km setup`")
            return 1
        acc = settings.resolve_account(name)
        existing = True
    else:
        existing = name in settings.sessions
        acc = settings.resolve_account(name) if existing else None

    # 已有账号:先免交互验证(服务器在线 = 会话已连接,直接判定有效)
    if existing and acc.session_file.exists():
        if _server_online(settings):
            logger.success("账号 '{}' 会话正常(服务器在线,会话已连接)", name)
            return 0
        print("→ 检测到已有会话文件,验证连接...")
        result = asyncio.run(login(acc))
        if result["ok"]:
            _save_me(acc, result)
            logger.success(
                "账号 '{}' 会话正常: {} (@{})",
                name,
                result["me"]["first_name"],
                result["me"]["username"] or "?",
            )
            return 0
        print(f"→ 会话已失效({result['reason']}),需要重新登录")
    if existing:
        return _cmd_relogin(settings, acc)

    # 新账号:凭据(默认复用顶层)→ 白名单 → 登录 → 成功才记录
    api_id = args.api_id
    api_hash = args.api_hash
    if api_id is None:
        default = str(settings.api_id) if settings.api_id else None
        raw = _ask("API_ID(my.telegram.org/apps)", default)
        if not raw:
            logger.error("API_ID 不能为空;可先 `km setup` 配置应用凭据后回车复用")
            return 1
        try:
            api_id = int(raw)
        except ValueError:
            logger.error("API_ID 必须是数字: {!r}", raw)
            return 1
    if not api_hash:
        api_hash = _ask("API_HASH", settings.api_hash if settings.api_hash else None, secret=True)
        if not api_hash:
            logger.error("API_HASH 不能为空")
            return 1
    proxy = args.proxy
    if proxy is None:
        proxy = _ask("代理(可选,如 socks5://127.0.0.1:1080)", None) or None
    allowed = args.allowed_chat_ids
    if allowed is None:
        allowed = _ask("白名单(逗号分隔,回车用全局)", None)
    allowed = (allowed or "").strip()

    try:
        session_store.validate_new_session(settings, name, api_id, api_hash)
    except McpError as exc:
        logger.error(exc.message)
        return 1

    tmp = Settings(
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy or settings.proxy,
        allowed_chat_ids=allowed or settings.allowed_chat_ids,
        account_name=name,
    )
    print(f"→ 开始登录 '{name}' ...")
    result = asyncio.run(login(tmp))
    if not result["ok"]:
        session_store.discard_failed_session(tmp, api_id)
        logger.error("账号 '{}' 未添加(登录失败): {}", name, result["reason"])
        logger.info("凭据未记录,半成品会话文件已清理;可重新运行 `km session add {}`", name)
        return 1

    session_store.register_session(
        settings, name, api_id, api_hash, proxy=proxy, allowed_chat_ids=allowed
    )
    _save_me(tmp, result)
    logger.success(
        "账号 '{}' 已添加并登录: {} (@{}) dc={}",
        name,
        result["me"]["first_name"],
        result["me"]["username"] or "?",
        result["me"]["dc"],
    )
    _maybe_restart(settings)
    return 0


def _cmd_relogin(settings: Settings, acc: Settings) -> int:
    """已有账号重登。"""
    name = acc.account_name or DEFAULT_ACCOUNT
    print(f"→ 重新登录 '{name}' ...")
    result = asyncio.run(login(acc))
    if result["ok"]:
        _save_me(acc, result)
        logger.success(
            "账号 '{}' 会话已刷新: {} (@{}) dc={}",
            name,
            result["me"]["first_name"],
            result["me"]["username"] or "?",
            result["me"]["dc"],
        )
        _maybe_restart(settings)
        return 0
    logger.error("账号 '{}' 重新登录失败: {};可重试 `km session add {}`", name, result["reason"], name)
    return 1


def _cmd_session_set(settings: Settings, args: argparse.Namespace) -> int:
    allowed = args.allowed_chat_ids
    proxy = args.proxy
    if allowed is None and proxy is None:
        # 交互模式:选账号 → 选字段 → 输入新值
        rows = session_store.list_sessions(settings)
        if not rows:
            logger.error("未配置任何账号;运行 `km session add` 添加")
            return 1
        idx = _pick(
            "选择账号:",
            [
                (
                    r["name"],
                    f"api_id={r['api_id']} {'✓' if r['logged_in'] else '✗ 未登录'}",
                )
                for r in rows
            ],
        )
        target = rows[idx]["name"]
        what = _pick("修改什么?", [("白名单", None), ("代理", None), ("都改", None)]) + 1
        if what in (1, 3):
            current = rows[idx]["allowed_chat_ids"] or "(全局)"
            raw = _ask(f"新白名单 [当前: {current}]", None)
            allowed = raw.strip() if raw else None
            if allowed is not None and not allowed:
                allowed = ""  # 显式清空 → 回退全局
        if what in (2, 3):
            current = rows[idx]["proxy"] or "-"
            raw = _ask(f"新代理 [当前: {current}]", None)
            proxy = raw.strip() if raw else None
        if allowed is None and proxy is None:
            print("未修改任何字段")
            return 0
    else:
        target = (args.name or "").strip()
        if not target:
            logger.error("需要账号名: km session set <name> --allowed-chat-ids ...")
            return 1

    try:
        result = session_store.set_session(
            settings, target, allowed_chat_ids=allowed, proxy=proxy
        )
    except McpError as exc:
        logger.error(exc.message)
        return 1
    logger.success(
        "账号 '{}' 已更新: 白名单={} 代理={}",
        result["name"],
        result["allowed_chat_ids"] or "(全局)",
        result["proxy"] or "-",
    )
    _maybe_restart(settings)
    return 0


def _cmd_session_remove(settings: Settings, args: argparse.Namespace) -> int:
    name = (args.name or "").strip()
    if not name:
        rows = session_store.list_sessions(settings)
        if not rows:
            logger.error("未配置任何账号")
            return 1
        idx = _pick("选择要删除的账号:", [(r["name"], f"api_id={r['api_id']}") for r in rows])
        name = rows[idx]["name"]
    try:
        result = session_store.remove_session(settings, name, force=args.force)
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


def _cmd_session_list(settings: Settings, args: argparse.Namespace) -> int:
    rows = session_store.list_sessions(settings)
    if not rows:
        logger.warning("未配置任何账号;运行 `km session add` 添加")
        return 0
    _print_account_table(rows, verbose=getattr(args, "verbose", False))
    return 0


# ---- 状态 / 重启 ----

def _cmd_status(settings: Settings) -> int:
    found = server_process()
    port = settings.port
    running = found is not None and port_open(port)
    if running:
        print(f"● 服务器: 运行中 http://127.0.0.1:{port}/mcp")
    else:
        print("○ 服务器: 未运行")
    rows = session_store.list_sessions(settings)
    if rows:
        _print_account_table(rows, verbose=False)
    else:
        print("(未配置任何账号)")
    if running:
        print("提示: 账号/白名单改动后需重启生效 → `km restart`")
    else:
        print("提示: `km run` 启动服务器")
    return 0


def _cmd_restart(settings: Settings) -> int:
    if not server_process():
        logger.error("没有找到运行中的服务器;请直接 `km run`")
        return 1
    return 0 if restart_server(settings) else 1


# ---- 入口 ----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kurigram-mcp",
        description="MCP server for debugging Telegram bots via a user session",
    )
    parser.add_argument("--version", action="version", version=f"kurigram-mcp {__version__}")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="启动 MCP 服务器")
    run_p.add_argument("--account", help="只启动指定账号(缺省:启动全部已注册账号;见 `session list`)")
    run_p.add_argument("--host", help="监听地址(默认取 HOST,127.0.0.1)")
    run_p.add_argument("--port", type=int, help="监听端口(默认取 PORT,8765)")
    run_p.add_argument("--path", default="/mcp", help="Streamable HTTP 端点路径(默认 /mcp)")
    run_p.add_argument(
        "--stateful", action="store_true", help="使用有状态会话模式(默认无状态,推荐)"
    )
    run_p.add_argument(
        "--json-response", action="store_true", help="纯 JSON 响应,不用 SSE(部分客户端不支持)"
    )

    session_p = sub.add_parser("session", help="账号管理:add(注册+登录)/ list / set / remove")
    session_p.add_argument("-v", "--verbose", action="store_true", help="list 时显示 proxy/白名单/登录时间等详情")
    session_sub = session_p.add_subparsers(dest="session_command")

    add_p = session_sub.add_parser("add", help="添加账号:注册 + 登录一条命令(不授权 = 不记录)")
    add_p.add_argument("name", nargs="?", help="账号名;缺省交互询问;已存在 = 重新登录")
    add_p.add_argument("--api-id", type=int, help="API_ID(缺省交互询问,可回车复用现有)")
    add_p.add_argument("--api-hash", help="API_HASH(缺省交互询问,getpass 隐藏输入)")
    add_p.add_argument("--proxy", help="该账号专用代理(可选)")
    add_p.add_argument("--allowed-chat-ids", help="该账号专用白名单(可选,逗号分隔;留空用全局)")

    set_p = session_sub.add_parser("set", help="修改账号配置(白名单/代理),重启服务器后生效")
    set_p.add_argument("name", nargs="?", help="账号名;缺省交互选择")
    set_p.add_argument("--allowed-chat-ids", help="新白名单(逗号分隔;传空字符串 '' 清除→回退全局)")
    set_p.add_argument("--proxy", help="新代理(传空字符串 '' 清除→直连/全局)")

    rm_p = session_sub.add_parser("remove", aliases=["rm"], help="删除账号(注册条目 + 会话文件)")
    rm_p.add_argument("name", nargs="?", help="账号名;缺省交互选择")
    rm_p.add_argument("-f", "--force", action="store_true", help="跳过确认(非交互环境必需)")

    session_sub.add_parser("list", aliases=["ls"], help="列出所有账号与登录状态")

    sub.add_parser("status", help="一眼总览:服务器状态 + 账号表")
    sub.add_parser("restart", help="重启运行中的服务器(账号/白名单改动后生效)")

    sub.add_parser("setup", help="交互式配置向导:生成 ~/.kurigram-mcp/config")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level)

    # 裸命令(无子命令):不启动服务器,打印帮助
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "setup":
        return run_setup()

    if args.command == "status":
        return _cmd_status(settings)

    if args.command == "restart":
        return _cmd_restart(settings)

    if args.command == "session":
        if session_store is None:  # pragma: no cover
            logger.error("sessions 模块不可用")
            return 1
        cmd = args.session_command or "list"
        if cmd == "add":
            return _cmd_session_add(settings, args)
        if cmd == "set":
            return _cmd_session_set(settings, args)
        if cmd == "remove" or cmd == "rm":
            return _cmd_session_remove(settings, args)
        return _cmd_session_list(settings, args)

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

    # --account 指定单账号(保留隔离模式);缺省启动全部已注册账号
    accounts: list[str] | None = None
    try:
        if getattr(args, "account", None):
            account = settings.resolve_account(args.account)
            if not account.session_file.exists():
                logger.error(
                    "账号 '{}' 未登录:未找到会话文件 {};请先运行 `km session add {}`",
                    account.account_name,
                    account.session_file,
                    account.account_name,
                )
                return 1
            accounts = [account.account_name]
    except McpError as exc:
        logger.error(exc.message)
        return 1

    logger.info(
        "kurigram-mcp v{} 启动中 (accounts={} transport=streamable-http)",
        __version__,
        ",".join(accounts) if accounts else "全部已注册",
    )
    run_server(settings, accounts=accounts, **overrides)
    return 0
