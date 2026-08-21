"""交互式配置:引导生成 ~/.kurigram-mcp/config.yaml。

只问真正需要人决策的项(凭据/白名单/代理);host/port/AUTH_TOKEN 用默认值
或保留已有值,不打扰用户。配置完成后直接进入登录向导(登录 default 账号),
可选择启动服务器。
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import yaml
from loguru import logger

from .config import default_config_file, home_dir


def _load_existing(path: Path) -> dict:
    """读取已有 YAML 配置,用于给默认值。"""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 配置损坏时按空处理
        return {}


def _ask(prompt: str, default: str | None = None, secret: bool = False) -> str:
    """交互输入;空输入返回默认值。"""
    label = f"{prompt} [默认: {default}]" if default else prompt
    try:
        if secret:
            import getpass

            value = getpass.getpass(label + ": ").strip()
            print()
        else:
            value = input(label + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(1) from None
    return value if value else (default or "")


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


def run_setup() -> int:
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    cfg_path = Path(default_config_file())
    existing = _load_existing(cfg_path)

    print("=== kurigram-mcp 配置向导 ===")
    print(f"配置文件: {cfg_path}\n")

    api_id = _ask(
        "API_ID(my.telegram.org/apps)", existing.get("api_id") and str(existing["api_id"])
    )
    api_hash = _ask("API_HASH", existing.get("api_hash"), secret=True)
    allowed = _ask(
        "ALLOWED_CHAT_IDS(逗号分隔:数字 id / @username / me,可留空)",
        existing.get("allowed_chat_ids"),
    )
    proxy = _ask("PROXY(可选,如 socks5://127.0.0.1:1080)", existing.get("proxy"))

    # host/port/AUTH_TOKEN 不再询问:保留已有值或默认(AUTH_TOKEN 自动生成)
    existing_token = existing.get("auth_token") or secrets.token_urlsafe(24)
    if not existing.get("auth_token"):
        print(
            f"\n🔑 已自动生成 AUTH_TOKEN:\n   {existing_token}\n   请复制到客户端配置(Authorization: Bearer {existing_token})"
        )

    data = {
        "api_id": int(api_id) if api_id else None,
        "api_hash": api_hash,
        "allowed_chat_ids": allowed,
        "proxy": proxy,
        "host": existing.get("host", "127.0.0.1"),
        "port": existing.get("port", 8765),
        "auth_token": existing_token,
        "strict_whitelist": bool(existing.get("strict_whitelist", False)),
    }
    cfg_path.write_text(
        "# kurigram-mcp 配置(由 `kurigram-mcp setup` 生成,修改后重启服务器生效)\n"
        + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    )
    os.chmod(cfg_path, 0o600)

    logger.success("配置已写入 {}", cfg_path)
    if not data["api_id"] or not data["api_hash"]:
        logger.warning("API_ID / API_HASH 未填写;之后可运行 `km session add default` 时补全")
        return 1

    # 直接进入登录向导(登录 default 账号)
    print("\n=== 登录默认账号(default)===\n")
    if not _confirm("现在登录 default 账号?", default=True):
        print("\n稍后运行 `km session add default` 完成登录")
        return 0

    import asyncio

    from .auth import login
    from .config import Settings
    from .sessions import make_me_snapshot, update_me

    result = asyncio.run(login(Settings(account_name="default")))
    if not result["ok"]:
        logger.error("登录失败: {}", result["reason"])
        logger.info("配置已保存;稍后运行 `km session add default` 重试")
        return 1
    update_me(
        Settings(account_name="default"),
        make_me_snapshot(**result["me"]),
    )
    logger.success(
        "登录成功: {} (@{}) dc={}",
        result["me"]["first_name"],
        result["me"]["username"] or "?",
        result["me"]["dc"],
    )

    if _confirm("启动服务器?", default=True):
        from .serverctl import spawn_server

        spawn_server()
        print("服务器启动中: http://127.0.0.1:8765/mcp(日志 /tmp/kurigram-server.log)")
    return 0
