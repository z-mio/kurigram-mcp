"""交互式登录:配置真实 API_ID/API_HASH 后,由用户亲自执行。"""

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
        logger.success(
            "登录成功: {} (@{}) [dc={}] 会话文件: {}",
            me.first_name,
            me.username or me.id,
            getattr(getattr(client, "session", None), "dc_id", "?"),
            session_file,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("登录失败: {}", to_mcp_error(exc).message)
        return 1
    finally:
        try:
            await client.stop()
        except Exception as exc:  # noqa: BLE001 - 停止失败不影响退出
            logger.debug("关闭客户端时出错: {}", exc)
