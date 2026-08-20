"""会话注册表与多账号解析测试。"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
import yaml

from kurigram_mcp.config import DEFAULT_ACCOUNT, Settings
from kurigram_mcp.errors import ACCOUNT_NOT_FOUND, McpError
from kurigram_mcp.sessions import (
    add_session,
    list_sessions,
    make_me_snapshot,
    remove_session,
    update_me,
)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """隔离的 KURIGRAM_MCP_HOME,避免触碰真实 ~/.kurigram-mcp。"""
    monkeypatch.setenv("KURIGRAM_MCP_HOME", str(tmp_path))
    return tmp_path


def _write_config(home: Path, data: dict) -> Path:
    path = home / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return path


def _settings() -> Settings:
    # 必须等 env(KURIGRAM_MCP_HOME)与 config.yaml 就绪后再构造
    return Settings()


# ---- ServerState 多账号解析 ----

def _fake_client(name: str):
    return types.SimpleNamespace(settings=types.SimpleNamespace(account_name=name), name=name)


def test_server_state_resolve_accounts():
    from kurigram_mcp.tools.common import ServerState

    state = ServerState(
        clients={"default": _fake_client("default"), "alice": _fake_client("alice")},
        accesses={},
        default="default",
        started_at=0,
    )
    # 缺省 = default
    assert state.resolve(None).name == "default"
    assert state.client.name == "default"
    # 具名
    assert state.resolve("alice").name == "alice"
    # 未知账号
    with pytest.raises(McpError) as ei:
        state.resolve("nobody")
    assert ei.value.code == ACCOUNT_NOT_FOUND
    with pytest.raises(McpError) as ei:
        state.resolve_access("nobody")
    assert ei.value.code == ACCOUNT_NOT_FOUND


def test_server_state_default_falls_to_first():
    from kurigram_mcp.tools.common import ServerState

    state = ServerState(
        clients={"alice": _fake_client("alice")},
        accesses={},
        default="alice",
        started_at=0,
    )
    assert state.resolve(None).name == "alice"


# ---- 注册表基础 ----

def test_settings_parses_sessions(home):
    _write_config(
        home,
        {
            "api_id": 111,
            "api_hash": "h111",
            "sessions": {
                "alice": {
                    "name": "alice",
                    "api_id": 222,
                    "api_hash": "h222",
                    "allowed_chat_ids": "123,456",
                }
            },
        },
    )
    s = _settings()
    assert s.api_id == 111
    assert list(s.sessions) == ["alice"]
    assert s.sessions["alice"].api_id == 222
    assert s.sessions["alice"].allowed_chat_ids == "123,456"


def test_account_names(home):
    _write_config(
        home,
        {"api_id": 111, "api_hash": "h111", "sessions": {"alice": {"name": "alice", "api_id": 222, "api_hash": "h222"}}},
    )
    s = _settings()
    assert s.account_names() == [DEFAULT_ACCOUNT, "alice"]

    _write_config(home, {"sessions": {"alice": {"name": "alice", "api_id": 222, "api_hash": "h222"}}})
    assert _settings().account_names() == ["alice"]


# ---- resolve_account ----

def test_resolve_legacy_default(home):
    _write_config(home, {"api_id": 111, "api_hash": "h111"})
    acc = _settings().resolve_account(None)
    assert acc.account_name == DEFAULT_ACCOUNT
    assert acc.api_id == 111
    assert acc.session_file.name == "u_111.session"


def test_resolve_named_account(home):
    _write_config(
        home,
        {
            "api_id": 111,
            "api_hash": "h111",
            "sessions": {
                "alice": {"name": "alice", "api_id": 222, "api_hash": "h222", "proxy": "socks5://x:1"},
                "bob": {"name": "bob", "api_id": 333, "api_hash": "h333"},
            },
        },
    )
    acc = _settings().resolve_account("bob")
    assert acc.account_name == "bob"
    assert acc.api_id == 333
    assert acc.api_hash == "h333"
    assert acc.session_file.name == "u_333.session"
    # proxy 未在账号上配置时回退全局
    acc2 = _settings().resolve_account("bob")
    assert acc2.proxy is None
    # alice 有自己 proxy
    assert _settings().resolve_account("alice").proxy == "socks5://x:1"


def test_resolve_first_when_no_legacy(home):
    _write_config(home, {"sessions": {"bob": {"name": "bob", "api_id": 333, "api_hash": "h333"}}})
    acc = _settings().resolve_account(None)
    assert acc.account_name == "bob"
    assert acc.api_id == 333


def test_resolve_missing_account(home):
    _write_config(home, {"api_id": 111, "api_hash": "h111"})
    with pytest.raises(McpError) as ei:
        _settings().resolve_account("nobody")
    assert ei.value.code == ACCOUNT_NOT_FOUND
    assert "nobody" in ei.value.message


def test_resolve_no_accounts(home):
    _write_config(home, {})
    with pytest.raises(McpError) as ei:
        _settings().resolve_account(None)
    assert ei.value.code == ACCOUNT_NOT_FOUND


def test_resolve_default_without_top_level(home):
    _write_config(home, {})
    with pytest.raises(McpError) as ei:
        _settings().resolve_account(DEFAULT_ACCOUNT)
    assert ei.value.code == ACCOUNT_NOT_FOUND


# ---- session add ----

def test_add_session_creates_config(home):
    s = _settings()  # 无 config
    result = add_session(s, "alice", 222, "h222", allowed_chat_ids="123")
    assert result["session_file"].endswith("u_222.session")
    cfg = home / "config.yaml"
    assert cfg.exists()
    assert cfg.stat().st_mode & 0o777 == 0o600
    data = yaml.safe_load(cfg.read_text())
    assert data["sessions"]["alice"]["api_id"] == 222
    assert data["sessions"]["alice"]["allowed_chat_ids"] == "123"
    assert "proxy" not in data["sessions"]["alice"]


def test_add_session_preserves_existing_keys(home):
    _write_config(home, {"api_id": 111, "api_hash": "h111", "auth_token": "tok", "port": 9000})
    add_session(_settings(), "alice", 222, "h222")
    data = yaml.safe_load((home / "config.yaml").read_text())
    assert data["auth_token"] == "tok"
    assert data["port"] == 9000
    assert data["api_id"] == 111


@pytest.mark.parametrize(
    "name",
    ["default", "ab!", "a" * 40, ""],
)
def test_add_session_bad_name(home, name):
    s = _settings()
    with pytest.raises(McpError):
        add_session(s, name, 222, "h222")


def test_add_session_trims_name(home):
    result = add_session(_settings(), "  alice  ", 222, "h222")
    assert result["name"] == "alice"
    data = yaml.safe_load((home / "config.yaml").read_text())
    assert "alice" in data["sessions"]


def test_add_session_duplicates(home):
    _write_config(home, {"api_id": 111, "api_hash": "h111"})
    s = _settings()
    add_session(s, "alice", 222, "h222")
    # 重名
    with pytest.raises(McpError) as ei:
        add_session(s, "alice", 333, "h333")
    assert "已存在" in ei.value.message
    # api_id 与顶层重复
    with pytest.raises(McpError) as ei:
        add_session(s, "bob", 111, "h333")
    assert "重复" in ei.value.message
    # api_id 与已有会话重复
    with pytest.raises(McpError) as ei:
        add_session(s, "bob", 222, "h333")
    assert "重复" in ei.value.message


def test_add_session_requires_hash(home):
    with pytest.raises(McpError):
        add_session(_settings(), "alice", 222, "  ")


# ---- session remove ----

def test_remove_named_session_deletes_file(home):
    session_file = home / "u_222.session"
    session_file.write_text("fake")
    _write_config(home, {"api_id": 111, "api_hash": "h111", "sessions": {"alice": {"name": "alice", "api_id": 222, "api_hash": "h222"}}})
    result = remove_session(_settings(), "alice", force=True)
    assert result["deleted_file"] is True
    assert not session_file.exists()
    data = yaml.safe_load((home / "config.yaml").read_text())
    assert data["sessions"] == {}
    assert data["api_id"] == 111  # 顶层不受影响


def test_remove_default_clears_top_level(home):
    session_file = home / "u_111.session"
    session_file.write_text("fake")
    _write_config(home, {"api_id": 111, "api_hash": "h111", "me": {"first_name": "x"}})
    result = remove_session(_settings(), DEFAULT_ACCOUNT, force=True)
    assert result["deleted_file"] is True
    data = yaml.safe_load((home / "config.yaml").read_text())
    assert "api_id" not in data
    assert "api_hash" not in data
    assert "me" not in data


def test_remove_missing_account(home):
    _write_config(home, {"api_id": 111, "api_hash": "h111"})
    with pytest.raises(McpError) as ei:
        remove_session(_settings(), "nobody", force=True)
    assert ei.value.code == ACCOUNT_NOT_FOUND


def test_remove_requires_confirm_outside_tty(home, monkeypatch):
    _write_config(home, {"sessions": {"alice": {"name": "alice", "api_id": 222, "api_hash": "h222"}}})
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(McpError) as ei:
        remove_session(_settings(), "alice")
    assert "force" in ei.value.message


# ---- me 快照回写 ----

def test_update_me_named_account(home):
    _write_config(home, {"sessions": {"alice": {"name": "alice", "api_id": 222, "api_hash": "h222", "proxy": "socks5://x:1"}}})
    s = _settings()
    snapshot = make_me_snapshot("Alice", "alice_user", 5)
    update_me(s.resolve_account("alice"), snapshot)
    data = yaml.safe_load((home / "config.yaml").read_text())
    assert data["sessions"]["alice"]["me"]["first_name"] == "Alice"
    assert data["sessions"]["alice"]["me"]["dc"] == 5
    assert data["sessions"]["alice"]["me"]["last_login"].endswith("Z")
    assert data["sessions"]["alice"]["proxy"] == "socks5://x:1"  # 其他字段保留


def test_update_me_default(home):
    _write_config(home, {"api_id": 111, "api_hash": "h111"})
    s = _settings()
    update_me(s.resolve_account(None), make_me_snapshot("Me", "me_user", 5))
    data = yaml.safe_load((home / "config.yaml").read_text())
    assert data["me"]["username"] == "me_user"


# ---- list_sessions ----

def test_list_sessions_rows(home):
    _write_config(
        home,
        {
            "api_id": 111,
            "api_hash": "h111",
            "me": {"first_name": "Me", "username": "me_user", "dc": 5, "last_login": "2026-01-01T00:00:00Z"},
            "sessions": {"alice": {"name": "alice", "api_id": 222, "api_hash": "h222"}},
        },
    )
    s = _settings()
    (home / "u_111.session").write_text("x")
    rows = list_sessions(s)
    assert [r["name"] for r in rows] == [DEFAULT_ACCOUNT, "alice"]
    assert rows[0]["logged_in"] is True
    assert rows[0]["me"]["username"] == "me_user"
    assert rows[1]["logged_in"] is False
    assert rows[1]["session_file"].endswith("u_222.session")


def test_list_sessions_empty(home):
    assert list_sessions(_settings()) == []
