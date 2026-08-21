"""交互式登录向导:`km session add` 的核心,不再作为独立子命令。

流程:手机号 → 验证码(最多 3 次)→ 两步验证密码;错误给出可操作的原因。
登录成功由调用方负责写入注册表与身份快照;失败由调用方决定清理或保留。
"""

from __future__ import annotations

import getpass

from loguru import logger
from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberUnoccupied,
    SessionPasswordNeeded,
)

from .config import Settings
from .telegram.client import parse_proxy


def _ask(prompt: str, secret: bool = False) -> str:
    try:
        if secret:
            return getpass.getpass(prompt + ": ").strip()
        return input(prompt + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(1) from None


def _ask_phone() -> str:
    while True:
        phone = _ask("手机号(含国家码,如 +8613800138000)")
        if phone:
            return phone
        print("✗ 手机号不能为空")


def _ask_code(attempt: int) -> str:
    hint = "验证码" if attempt == 0 else f"验证码(第 {attempt + 1}/3 次)"
    while True:
        code = _ask(hint)
        if code:
            return code
        print("✗ 验证码不能为空")


async def _authorize(client: Client, phone: str | None) -> tuple[bool, str | None, object | None]:
    """执行授权流程;返回 (ok, reason, user)。

    user 为 sign_in/check_password 返回的 User(已授权会话为 None,由调用方 get_me)。
    """
    # 会话文件有效(connect 已加载 storage)
    if await client.storage.user_id():
        return True, None, None

    phone = phone or _ask_phone()
    try:
        sent = await client.send_phone_number_code(phone)
    except FloodWait as exc:
        return False, f"发送验证码触发限流,请等待 {getattr(exc, 'value', '?')} 秒后重试", None
    except PhoneNumberUnoccupied:
        return False, f"手机号 {phone} 未注册 Telegram;请检查国家码或号码", None
    except Exception as exc:  # noqa: BLE001
        return False, f"发送验证码失败: {type(exc).__name__}: {exc}", None

    user: object | None = None
    for attempt in range(3):
        code = _ask_code(attempt)
        try:
            user = await client.sign_in(phone, sent.phone_code_hash, code)
            break
        except PhoneCodeInvalid:
            if attempt == 2:
                return False, "验证码错误次数过多,请重新运行", None
            print("✗ 验证码错误,重试")
        except PhoneCodeExpired:
            return False, "验证码已过期,请重新运行发送新验证码", None
        except SessionPasswordNeeded:
            break  # 进入两步验证
        except FloodWait as exc:
            return False, f"登录触发限流,请等待 {getattr(exc, 'value', '?')} 秒后重试", None
        except Exception as exc:  # noqa: BLE001
            return False, f"登录失败: {type(exc).__name__}: {exc}", None
    else:
        return False, "验证码错误次数过多,请重新运行", None

    # 两步验证(2FA)
    if user is None and not await client.storage.user_id():
        for attempt in range(3):
            password = _ask("两步验证密码(2FA)", secret=True)
            try:
                user = await client.check_password(password)
                break
            except PasswordHashInvalid:
                if attempt == 2:
                    return False, "两步验证密码错误次数过多,请稍后再试", None
                print("✗ 密码错误,重试")
            except FloodWait as exc:
                return False, f"登录触发限流,请等待 {getattr(exc, 'value', '?')} 秒后重试", None
            except Exception as exc:  # noqa: BLE001
                return False, f"两步验证失败: {type(exc).__name__}: {exc}", None
        else:
            return False, "两步验证密码错误次数过多,请稍后再试", None

    return True, None, user


async def login(settings: Settings, phone: str | None = None) -> dict:
    """引导式登录并保存会话。返回 {ok, reason, me, dc}。

    - 会话文件有效 → 直接验证,免交互;
    - 会话文件失效/不存在 → 交互登录(手机号 → 验证码 → 2FA);
    - 失败原因(result["reason"])由调用方展示;文件清理由调用方负责。
    """
    result: dict = {"ok": False, "reason": None, "me": None, "dc": None}
    settings.require_credentials()
    settings.ensure_dirs()

    client = Client(
        f"u_{settings.api_id}",
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        workdir=settings.sessions_dir,
        proxy=parse_proxy(settings.proxy),
    )
    try:
        await client.connect()  # 返回是否已授权;加载/创建会话
        ok, reason, user = await _authorize(client, phone)
        if not ok:
            result["reason"] = reason
            return result
        me = user or await client.get_me()
        dc = getattr(getattr(client, "session", None), "dc_id", None)
        result.update(
            ok=True,
            me={
                "first_name": getattr(me, "first_name", "") or "",
                "username": getattr(me, "username", None),
                "dc": dc,
            },
            dc=dc,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        try:
            await client.stop()  # 授权成功会保存会话;失败不保存有效会话
        except Exception as exc:  # noqa: BLE001 - 停止失败不影响结果
            logger.debug("关闭客户端时出错: {}", exc)
