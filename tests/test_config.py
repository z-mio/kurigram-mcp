"""Settings 配置解析测试。"""

from __future__ import annotations

from kurigram_mcp.config import Settings, default_session_dir
from kurigram_mcp.errors import McpError


def test_defaults(monkeypatch) -> None:
    for key in ("API_ID", "API_HASH", "ALLOWED_CHAT_IDS", "AUTH_TOKEN", "PROXY"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.host == "127.0.0.1"
    assert s.port == 8765
    assert s.allowed_chat_ids == ""
    assert s.session_name == "kurigram"
    # 未配置 API_ID 时退回默认会话名
    assert str(s.session_file).endswith("kurigram.session")
    # XDG 持久化:无 .env(uvx 模式)时默认目录在用户数据目录
    s2 = Settings(_env_file=None, session_dir=default_session_dir())
    assert s2.session_dir == default_session_dir()


def test_session_dir_dev_mode_uses_cwd(monkeypatch, tmp_path) -> None:
    """开发模式(当前目录有 .env)时,会话文件留在当前目录,向后兼容。"""
    (tmp_path / ".env").write_text("API_ID=1\n")
    monkeypatch.chdir(tmp_path)
    s = Settings(_env_file=None)
    assert s.session_dir == "."


def test_session_dir_xdg_mode_without_env(monkeypatch, tmp_path) -> None:
    """uvx 模式(无 .env)时,会话文件落到 KURIGRAM_MCP_HOME 数据目录。"""
    monkeypatch.chdir(tmp_path)
    s = Settings(_env_file=None)
    import os

    assert s.session_dir == os.environ.get("KURIGRAM_MCP_HOME")


def test_session_file_binds_api_id(monkeypatch) -> None:
    """会话文件名与 API_ID 绑定:u_{api_id}.session。"""
    monkeypatch.setenv("API_ID", "12345")
    monkeypatch.delenv("SESSION_DIR", raising=False)
    s = Settings(_env_file=None)
    assert s.session_file.name == "u_12345.session"


def test_env_parsing(monkeypatch) -> None:
    monkeypatch.setenv("API_ID", "12345")
    monkeypatch.setenv("API_HASH", "abcdef")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "-1001,@bot,me")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("STRICT_WHITELIST", "true")
    s = Settings(_env_file=None)
    assert s.api_id == 12345
    assert s.api_hash == "abcdef"
    assert s.allowed_chat_ids == "-1001,@bot,me"
    assert s.port == 9000
    assert s.strict_whitelist is True


def test_require_credentials(monkeypatch) -> None:
    monkeypatch.delenv("API_ID", raising=False)
    monkeypatch.delenv("API_HASH", raising=False)
    s = Settings(_env_file=None)
    try:
        s.require_credentials()
    except McpError as exc:
        assert exc.code == "SESSION_INVALID"
    else:
        raise AssertionError("缺少凭据时应抛 McpError")


def test_yaml_config_loading(monkeypatch, tmp_path) -> None:
    """YAML 主配置读取 + 优先级:环境变量 > YAML > 项目 .env。"""
    (tmp_path / "config.yaml").write_text("api_id: 555\nallowed_chat_ids: yaml_value\nport: 9001\n")
    monkeypatch.setenv("KURIGRAM_MCP_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # 无项目 .env

    # 无环境变量:YAML 生效
    s = Settings(_env_file=None)
    assert s.api_id == 555
    assert s.allowed_chat_ids == "yaml_value"
    assert s.port == 9001

    # 环境变量覆盖 YAML
    monkeypatch.setenv("PORT", "7777")
    s2 = Settings(_env_file=None)
    assert s2.port == 7777
    assert s2.api_id == 555

    # 项目 .env 兜底(无 YAML 键时)
    monkeypatch.delenv("PORT")
    (tmp_path / ".env").write_text("ALLOWED_CHAT_IDS=dotenv_value\n")
    s3 = Settings()
    assert s3.allowed_chat_ids == "yaml_value"  # YAML 优先于 dotenv


def test_setup_generates_yaml_with_token(monkeypatch, tmp_path, capsys) -> None:
    """setup 生成 YAML 配置;AUTH_TOKEN 留空自动生成。"""
    import kurigram_mcp.setup as setup_mod

    monkeypatch.setenv("KURIGRAM_MCP_HOME", str(tmp_path))
    inputs = iter(["12345", "hash_value", "6540476263", "", "127.0.0.1", "8765", "", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(setup_mod, "home_dir", lambda: tmp_path)

    rc = setup_mod.run_setup()
    cfg = tmp_path / "config.yaml"
    assert rc == 0
    assert cfg.exists()
    import yaml

    data = yaml.safe_load(cfg.read_text())
    assert data["api_id"] == 12345
    assert data["api_hash"] == "hash_value"
    assert data["allowed_chat_ids"] == "6540476263"
    assert data["auth_token"]  # 自动生成
    assert len(data["auth_token"]) >= 20
    out = capsys.readouterr().out
    assert "自动生成" in out  # 提示用户复制 token


def test_setup_y_enters_auth(monkeypatch, tmp_path) -> None:
    """setup 结尾选 y → 直接进入 auth。"""
    import kurigram_mcp.setup as setup_mod

    monkeypatch.setenv("KURIGRAM_MCP_HOME", str(tmp_path))
    inputs = iter(["12345", "hash_value", "6540476263", "", "127.0.0.1", "8765", "", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(setup_mod, "home_dir", lambda: tmp_path)

    called = {"auth": False}

    async def fake_auth(settings):
        called["auth"] = True
        return 7

    monkeypatch.setattr("kurigram_mcp.auth.run_auth", fake_auth)

    rc = setup_mod.run_setup()
    assert rc == 7  # auth 的返回值透传
    assert called["auth"]
