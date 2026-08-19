"""交互式配置:引导生成 ~/.kurigram-mcp/config.yaml。

不需要用户手动编辑文件;重复运行会保留已有值作为默认;
AUTH_TOKEN 留空时自动生成随机 token(默认启用 Bearer 鉴权)。
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
    if default:
        prompt = f"{prompt} [默认: {default}]"
    value = input(f"{prompt}: ").strip()
    if not value and default:
        return default
    return value


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
    host = _ask("HOST(默认 127.0.0.1)", existing.get("host", "127.0.0.1"))
    port = _ask("PORT(默认 8765)", existing.get("port") and str(existing["port"]))

    # AUTH_TOKEN:留空自动生成(默认开启 Bearer 鉴权)
    existing_token = existing.get("auth_token")
    token_input = _ask("AUTH_TOKEN(留空自动生成)", existing_token, secret=True)
    auth_token = token_input or (existing_token or secrets.token_urlsafe(24))
    if not token_input and not existing_token:
        print(
            f"\n🔑 已自动生成 AUTH_TOKEN:\n   {auth_token}\n   请复制到客户端配置(Authorization: Bearer {auth_token})"
        )

    data = {
        "api_id": int(api_id) if api_id else None,
        "api_hash": api_hash,
        "allowed_chat_ids": allowed,
        "proxy": proxy,
        "host": host,
        "port": int(port) if port else 8765,
        "auth_token": auth_token,
        "strict_whitelist": bool(existing.get("strict_whitelist", False)),
    }
    cfg_path.write_text(
        "# kurigram-mcp 配置(由 `kurigram-mcp setup` 生成,修改后重启服务器生效)\n"
        + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    )
    os.chmod(cfg_path, 0o600)

    logger.success("配置已写入 {}", cfg_path)
    if not data["api_id"] or not data["api_hash"]:
        logger.warning("API_ID / API_HASH 未填写,请补全后继续;之后可运行 `kurigram-mcp auth` 登录")
        return 1

    # 一键登录:配置完成后直接进入 auth 交互
    choice = input("\n是否立即进行 Telegram 登录(auth)?[Y/n]: ").strip().lower()
    if choice in ("", "y", "yes"):
        import asyncio

        from .auth import run_auth
        from .config import Settings

        print("\n=== 开始登录(手机号 -> 验证码 -> 2FA)===\n")
        return asyncio.run(run_auth(Settings()))

    print("\n稍后运行 `kurigram-mcp auth` 完成登录")
    return 0
