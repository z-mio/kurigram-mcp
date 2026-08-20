"""交互式登录:配置真实 API_ID/API_HASH 后,由用户亲自执行。

支持多账号:settings.account_name 标识当前账号(auth 由 CLI 解析后传入),
登录成功后把身份快照写回会话注册表(config.yaml),供 `session list` 离线展示。
"""

from __future__ import annotations

from loguru import logger
from pyrogram import Client

from .config import Settings
from .errors import to_mcp_error
from .telegram.client import parse_proxy


async def run_auth(settings: Settings) -> int:
    settings.require_credentials()
    settings.ensure_dirs()

    session_file = settings.session_file
    if session_file.exists():
        logger.info("发现已有会话 {},将直接连接验证", session_file)
    else:
        logger.info("未找到会话,开始交互式登录(手机号 -> 验证码 -> 2FA 密码)")

    client = Client(
        f"u_{settings.api_id}",
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        workdir=settings.session_dir,
        proxy=parse_proxy(settings.proxy),
    )
    try:
        await client.start()
        me = await client.get_me()
        dc = getattr(getattr(client, "session", None), "dc_id", None)
        logger.success(
            "登录成功: {} (@{}) [dc={}] 账号={} 会话文件: {}",
            me.first_name,
            me.username or me.id,
            dc,
            settings.account_name or "default",
            session_file,
        )
        _save_me_snapshot(settings, me, dc)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("登录失败: {}", to_mcp_error(exc).message)
        return 1
    finally:
        try:
            await client.stop()
        except Exception as exc:  # noqa: BLE001 - 停止失败不影响退出
            logger.debug("关闭客户端时出错: {}", exc)


def _save_me_snapshot(settings: Settings, me, dc: int | None) -> None:
    """把身份快照写回注册表;失败只告警,不影响登录结果。"""
    try:
        from .sessions import make_me_snapshot, update_me

        update_me(
            settings,
            make_me_snapshot(
                first_name=me.first_name or "",
                username=getattr(me, "username", None),
                dc=dc,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("写回身份快照失败(不影响登录): {}", exc)
