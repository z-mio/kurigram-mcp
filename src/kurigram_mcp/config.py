"""运行时配置。

配置加载优先级(高 → 低):
1. 环境变量(stdio 模式/临时覆盖用)
2. ~/.kurigram-mcp/config.yaml(setup 交互式生成的主配置,YAML)
3. 当前工作目录的 .env(开发模式兼容)

数据目录:默认 ~/.kurigram-mcp(会话文件、下载),可用 SESSION_DIR 覆盖。
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .errors import SESSION_INVALID, McpError


def home_dir() -> Path:
    """数据/配置根目录:~/.kurigram-mcp(可用 KURIGRAM_MCP_HOME 覆盖)。"""
    return Path(os.environ.get("KURIGRAM_MCP_HOME") or str(Path.home() / ".kurigram-mcp"))


def default_session_dir() -> str:
    return str(home_dir())


def default_config_file() -> str:
    """主配置文件(setup 交互式生成,YAML)。"""
    return str(home_dir() / "config.yaml")


class Settings(BaseSettings):
    """字段名:YAML 用小写字段名;环境变量用大写(如 ALLOWED_CHAT_IDS)。"""

    model_config = SettingsConfigDict(
        env_file=str(Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: InitSettingsSource,
        env_settings: EnvSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """来源顺序:init > 环境变量 > YAML 主配置 > 项目 .env。"""
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=default_config_file()),
            dotenv_settings,
        )

    # ---- Telegram 凭据(必填,来自 https://my.telegram.org/apps)----
    api_id: int | None = None
    api_hash: str | None = None

    # ---- 会话(固定 ~/.kurigram-mcp,持久化;可用 SESSION_DIR 覆盖)----
    session_name: str = "kurigram"
    session_dir: str = Field(default_factory=default_session_dir)

    # ---- 聊天白名单(基础兜底;HTTP 模式下可用请求头 X-Kurigram-Allowed-Chats 覆盖)----
    allowed_chat_ids: str = ""
    strict_whitelist: bool = False

    # ---- MCP 服务器 ----
    host: str = "127.0.0.1"
    port: int = 8765
    auth_token: str | None = None

    # ---- 网络 ----
    proxy: str | None = None

    # ---- 日志 ----
    log_level: str = "INFO"

    @property
    def session_file(self) -> Path:
        """会话文件与 API_ID 绑定:u_{api_id}.session;未配置 api_id 时退回 session_name。"""
        name = f"u_{self.api_id}" if self.api_id else self.session_name
        return Path(self.session_dir) / f"{name}.session"

    @property
    def downloads_dir(self) -> Path:
        return Path(self.session_dir) / "downloads"

    def ensure_dirs(self) -> None:
        """确保会话/数据目录存在(登录与服务器启动时调用)。"""
        Path(self.session_dir).mkdir(parents=True, exist_ok=True)

    def require_credentials(self) -> None:
        if not self.api_id or not self.api_hash:
            raise McpError(
                SESSION_INVALID,
                "缺少 API_ID / API_HASH。请运行 `kurigram-mcp setup` 交互式配置"
                "(写入 ~/.kurigram-mcp/config.yaml),或设置环境变量",
            )
