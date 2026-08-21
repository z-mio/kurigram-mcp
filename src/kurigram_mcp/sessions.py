"""会话注册表:config.yaml 中 sessions 段的增删查。

与 Settings 的关系:
- 顶层 api_id/api_hash = 隐式账号 "default"(setup 生成,向后兼容);
- sessions: 命名账号字典,由 `kurigram-mcp session add` 管理;
- 注册表写入是"原样 dict 改写",保留其他未知键(host/port/auth_token/注释外键)。
"""

from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from loguru import logger

from .config import DEFAULT_ACCOUNT, Settings
from .errors import ACCOUNT_NOT_FOUND, McpError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_HEADER = "# kurigram-mcp 配置(由 `kurigram-mcp setup` / `session` 命令维护,修改后重启服务器生效)\n"


# ---- 底层读写 ----

def load_raw(path: Path | None = None) -> dict:
    """读取 config.yaml 原始 dict;文件缺失/损坏时返回 {}。"""
    path = path or default_config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 配置损坏时按空处理,避免阻塞会话管理
        return {}


def save_raw(data: dict, path: Path | None = None) -> None:
    """写回 config.yaml(0o600),保留其他未知键。"""
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEADER + yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    os.chmod(path, 0o600)


def default_config_path() -> Path:
    from .config import default_config_file

    return Path(default_config_file())


def _session_file(settings: Settings, api_id: int) -> Path:
    return settings.sessions_dir / f"u_{api_id}.session"


# ---- 查询 ----

def list_sessions(settings: Settings) -> list[dict]:
    """按展示顺序返回账号行:default 优先,随后是命名账号。"""
    data = load_raw()
    rows: list[dict] = []
    if settings.api_id:
        me = data.get("me")
        rows.append(
            {
                "name": DEFAULT_ACCOUNT,
                "api_id": settings.api_id,
                "api_hash": settings.api_hash,
                "proxy": settings.proxy,
                "allowed_chat_ids": settings.allowed_chat_ids,
                "me": me,
                "session_file": str(_session_file(settings, settings.api_id)),
                "logged_in": _session_file(settings, settings.api_id).exists(),
            }
        )
    for entry in settings.sessions.values():
        rows.append(
            {
                "name": entry.name,
                "api_id": entry.api_id,
                "api_hash": entry.api_hash,
                "proxy": entry.proxy,
                "allowed_chat_ids": entry.allowed_chat_ids,
                "me": entry.me.model_dump() if entry.me else None,
                "session_file": str(_session_file(settings, entry.api_id)),
                "logged_in": _session_file(settings, entry.api_id).exists(),
            }
        )
    return rows


# ---- 增删 ----

def validate_new_session(
    settings: Settings,
    name: str,
    api_id: int,
    api_hash: str,
) -> None:
    """校验新账号参数(名字格式/保留字/重名/重复 api_id);不合法抛 McpError。

    登录前调用:避免用户白输一遍手机号验证码。
    """
    name = name.strip()
    if not _NAME_RE.match(name):
        raise McpError(
            ACCOUNT_NOT_FOUND,
            f"账号名 '{name}' 非法:仅允许字母/数字/下划线/连字符,2-32 字符,首字符须为字母或数字",
        )
    if name == DEFAULT_ACCOUNT:
        raise McpError(ACCOUNT_NOT_FOUND, f"'{DEFAULT_ACCOUNT}' 是保留账号名(对应顶层配置),请换一个名字")
    if not isinstance(api_id, int) or api_id <= 0:
        raise McpError(ACCOUNT_NOT_FOUND, f"API_ID 非法: {api_id!r}")
    if not api_hash or not api_hash.strip():
        raise McpError(ACCOUNT_NOT_FOUND, "API_HASH 不能为空")

    data = load_raw()
    sessions = data.get("sessions") or {}
    if name in sessions:
        raise McpError(ACCOUNT_NOT_FOUND, f"账号 '{name}' 已存在;重新登录请直接 `session add {name}`")
    taken_ids = {s.get("api_id") for s in sessions.values() if isinstance(s, dict) and s.get("api_id")}
    if settings.api_id:
        taken_ids.add(settings.api_id)
    if api_id in taken_ids:
        raise McpError(ACCOUNT_NOT_FOUND, f"API_ID {api_id} 已被其他账号使用,不能重复注册")


def register_session(
    settings: Settings,
    name: str,
    api_id: int,
    api_hash: str,
    proxy: str | None = None,
    allowed_chat_ids: str = "",
) -> dict:
    """登录成功后把账号写入注册表(不登录;登录由 auth.login 负责)。"""
    validate_new_session(settings, name, api_id, api_hash)
    name = name.strip()

    data = load_raw()
    sessions = data.setdefault("sessions", {})
    sessions[name] = {
        "name": name,
        "api_id": api_id,
        "api_hash": api_hash.strip(),
        **({"proxy": proxy} if proxy else {}),
        **({"allowed_chat_ids": allowed_chat_ids} if allowed_chat_ids else {}),
    }
    save_raw(data)
    return {"name": name, "api_id": api_id, "session_file": str(_session_file(settings, api_id))}


def discard_failed_session(settings: Settings, api_id: int) -> None:
    """登录失败后清理:删除半成品会话文件(含日志),注册表未写入所以无需改动。"""
    target = _session_file(settings, api_id)
    for path in (target, Path(str(target) + "-journal")):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.debug("清理半成品会话文件失败: {}", path)


def set_session(
    settings: Settings,
    name: str,
    allowed_chat_ids: str | None = None,
    proxy: str | None = None,
) -> dict:
    """更新账号配置(白名单/代理)。

    None = 保持原值;空字符串 = 清除(白名单清除后回退全局,代理清除后走全局/直连)。
    default 账号的白名单即顶层 allowed_chat_ids。
    """
    data = load_raw()
    name = name.strip()

    if name == DEFAULT_ACCOUNT:
        if not settings.api_id:
            raise McpError(ACCOUNT_NOT_FOUND, f"账号 '{DEFAULT_ACCOUNT}' 未配置,无需修改")
        if allowed_chat_ids is not None:
            data["allowed_chat_ids"] = allowed_chat_ids
        if proxy is not None:
            if proxy:
                data["proxy"] = proxy
            else:
                data.pop("proxy", None)
        save_raw(data)
        return {
            "name": name,
            "allowed_chat_ids": data.get("allowed_chat_ids", ""),
            "proxy": data.get("proxy"),
        }

    sessions = data.get("sessions") or {}
    entry = sessions.get(name)
    if not entry or not isinstance(entry, dict):
        raise McpError(ACCOUNT_NOT_FOUND, f"账号 '{name}' 不存在;运行 `kurigram-mcp session list` 查看")
    if allowed_chat_ids is not None:
        if allowed_chat_ids:
            entry["allowed_chat_ids"] = allowed_chat_ids
        else:
            entry.pop("allowed_chat_ids", None)  # 清除 → 回退全局
    if proxy is not None:
        if proxy:
            entry["proxy"] = proxy
        else:
            entry.pop("proxy", None)
    sessions[name] = entry
    data["sessions"] = sessions
    save_raw(data)
    return {
        "name": name,
        "allowed_chat_ids": entry.get("allowed_chat_ids", ""),
        "proxy": entry.get("proxy"),
    }


def remove_session(settings: Settings, name: str, force: bool = False) -> dict:
    """删除账号:注册表条目 + 会话文件(含旧布局位置)。default 只清顶层凭据。"""
    data = load_raw()
    name = name.strip()

    if name == DEFAULT_ACCOUNT:
        if not settings.api_id:
            raise McpError(ACCOUNT_NOT_FOUND, f"账号 '{DEFAULT_ACCOUNT}' 未配置,无需删除")
        api_id = settings.api_id
        target = _session_file(settings, api_id)
        _confirm_or_force(name, target, force)
        data.pop("api_id", None)
        data.pop("api_hash", None)
        data.pop("me", None)
    else:
        sessions = data.get("sessions") or {}
        entry = sessions.get(name)
        if not entry or not isinstance(entry, dict):
            raise McpError(ACCOUNT_NOT_FOUND, f"账号 '{name}' 不存在;运行 `kurigram-mcp session list` 查看")
        api_id = entry.get("api_id")
        target = _session_file(settings, api_id) if isinstance(api_id, int) else None
        _confirm_or_force(name, target, force)
        sessions.pop(name, None)
        data["sessions"] = sessions

    save_raw(data)
    deleted_file = False
    if target and target.exists():
        target.unlink()
        deleted_file = True
    logger.info("已删除账号 '{}' (api_id={}) 会话文件删除={}", name, api_id, deleted_file)
    return {"name": name, "api_id": api_id, "session_file": str(target), "deleted_file": deleted_file}


def _confirm_or_force(name: str, session_file: Path | None, force: bool) -> None:
    if force:
        return
    if not sys.stdin.isatty():
        raise McpError(
            ACCOUNT_NOT_FOUND,
            f"删除账号 '{name}' 需要确认;非交互环境请加 -f/--force",
        )
    hint = f" 及其会话文件 {session_file}" if session_file else ""
    answer = input(f"将删除账号 '{name}'{hint},确认?[y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        raise McpError(ACCOUNT_NOT_FOUND, "已取消删除")


# ---- 登录快照回写 ----

def update_me(settings: Settings, me: dict) -> None:
    """登录成功后把身份快照写回注册表(default 写顶层 me,命名账号写 sessions[name].me)。"""
    data = load_raw()
    name = settings.account_name or DEFAULT_ACCOUNT
    if name == DEFAULT_ACCOUNT:
        data["me"] = me
    else:
        sessions = data.setdefault("sessions", {})
        entry = sessions.get(name)
        if entry and isinstance(entry, dict):
            entry["me"] = me
    save_raw(data)


def make_me_snapshot(first_name: str, username: str | None, dc: int | None) -> dict:
    """构造 me 快照 dict(带当前 UTC 时间)。"""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {"first_name": first_name, "username": username, "dc": dc, "last_login": now}
