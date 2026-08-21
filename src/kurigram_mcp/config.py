"""运行时配置。

配置加载优先级(高 → 低):
1. 环境变量(stdio 模式/临时覆盖用)
2. ~/.kurigram-mcp/config.yaml(setup 交互式生成的主配置,YAML)
3. 当前工作目录的 .env(开发模式兼容)

数据目录:默认 ~/.kurigram-mcp(可用 SESSION_DIR 覆盖),结构:
- config.yaml / downloads / 其他 → 根下
- 会话文件 → sessions/ 子目录(u_{api_id}.session)
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .errors import ACCOUNT_NOT_FOUND, SESSION_INVALID, McpError

# 隐式账号名:顶层 api_id/api_hash 对应的旧式单账号配置(setup 生成)
DEFAULT_ACCOUNT = "default"


class MeSnapshot(BaseModel):
    """登录成功后缓存的账号身份,供 `session list` 离线展示。"""

    first_name: str = ""
    username: str | None = None
    dc: int | None = None
    last_login: str = ""


class SessionEntry(BaseModel):
    """注册表中的一个命名账号(sessions 段的条目)。"""

    name: str
    api_id: int
    api_hash: str
    proxy: str | None = None
    # 每账号独立白名单;留空则回退全局 allowed_chat_ids
    allowed_chat_ids: str = ""
    me: MeSnapshot | None = None


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
        """来源顺序:init > 环境变量 > ~/.kurigram-mcp/config.yaml。

        刻意不读取当前目录的 .env:避免在其他项目目录启动时配置串台。
        """
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=default_config_file()),
        )

    # ---- Telegram 凭据(必填,来自 https://my.telegram.org/apps)----
    api_id: int | None = None
    api_hash: str | None = None

    # ---- 会话(固定 ~/.kurigram-mcp,持久化;可用 SESSION_DIR 覆盖)----
    session_dir: str = Field(default_factory=default_session_dir)

    # ---- 多账号注册表:命名账号(由 `kurigram-mcp session add` 管理)----
    # 顶层 api_id/api_hash 构成隐式账号 "default";sessions 为命名账号字典。
    sessions: dict[str, SessionEntry] = {}

    # 当前解析出的账号名(resolve_account 设置,用于日志/快照回写)
    account_name: str | None = None

    # ---- 聊天白名单(全局兜底;账号级 sessions.<name>.allowed_chat_ids 可覆盖)----
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
    def sessions_dir(self) -> Path:
        """会话文件目录:session_dir/sessions(与配置/下载分离,2026-08 起)。"""
        return Path(self.session_dir) / "sessions"

    @property
    def session_file(self) -> Path:
        """会话文件与 API_ID 绑定:sessions/u_{api_id}.session(无回退名)。"""
        if not self.api_id:
            raise McpError(
                SESSION_INVALID,
                "缺少 API_ID,无法确定会话文件名;请运行 `kurigram-mcp setup` 交互式配置"
                "(写入 ~/.kurigram-mcp/config.yaml),或设置环境变量",
            )
        return self.sessions_dir / f"u_{self.api_id}.session"

    @property
    def downloads_dir(self) -> Path:
        return Path(self.session_dir) / "downloads"

    def ensure_dirs(self) -> None:
        """确保数据/会话目录存在(登录与服务器启动时调用)。"""
        Path(self.session_dir).mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def require_credentials(self) -> None:
        if not self.api_id or not self.api_hash:
            raise McpError(
                SESSION_INVALID,
                "缺少 API_ID / API_HASH。请运行 `kurigram-mcp setup` 交互式配置"
                "(写入 ~/.kurigram-mcp/config.yaml),或设置环境变量",
            )

    # ---- 多账号解析 ----

    def account_names(self) -> list[str]:
        """可用账号名列表:隐式 default 优先,随后是注册的命名账号。"""
        names = [DEFAULT_ACCOUNT] if self.api_id else []
        names += list(self.sessions)
        return names

    def resolve_account(self, name: str | None) -> Settings:
        """把账号名解析为一份完整的账号 Settings 副本。

        - name 为 None:隐式 default 优先,否则取第一个注册会话;
        - name == "default":顶层 api_id/api_hash;
        - 其他:必须在 sessions 注册表中存在。
        返回的副本 api_id/api_hash/proxy/白名单 已按账号覆盖,
        account_name 已设置,可直接用于 auth / run。
        """
        if name == DEFAULT_ACCOUNT:
            if not self.api_id:
                raise McpError(
                    ACCOUNT_NOT_FOUND,
                    f"账号 '{DEFAULT_ACCOUNT}' 未配置(顶层 API_ID 为空);"
                    "请运行 `kurigram-mcp setup` 或 `kurigram-mcp session add`",
                )
            return Settings(
                api_id=self.api_id,
                api_hash=self.api_hash,
                proxy=self.proxy,
                allowed_chat_ids=self.allowed_chat_ids,
                account_name=DEFAULT_ACCOUNT,
            )
        if name is not None:
            entry = self.sessions.get(name)
            if not entry:
                raise McpError(
                    ACCOUNT_NOT_FOUND,
                    f"账号 '{name}' 不存在;运行 `kurigram-mcp session list` 查看可用账号",
                )
            return Settings(
                api_id=entry.api_id,
                api_hash=entry.api_hash,
                proxy=entry.proxy or self.proxy,
                allowed_chat_ids=entry.allowed_chat_ids or self.allowed_chat_ids,
                account_name=entry.name,
            )
        if self.api_id:
            return self.resolve_account(DEFAULT_ACCOUNT)
        if self.sessions:
            return self.resolve_account(next(iter(self.sessions)))
        raise McpError(
            ACCOUNT_NOT_FOUND,
            "未配置任何账号;运行 `kurigram-mcp setup` 或 `kurigram-mcp session add`",
        )
