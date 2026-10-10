"""HTTP 文件网关:签名 URL(presigned)授权的上传/下载侧端点。

远程 MCP 客户端拿不到服务器本地文件,因此提供两条旁路:
- 下载:get_media_url 签发短时效 URL,GET /files/{chat_id}/{message_id} 直接拉媒体(支持 Range);
- 上传:create_upload_url 签发一次性 URL,PUT /upload/{name} 落盘 uploads/<uid>/<name>,
  发送工具以 upload://<uid>/<name> 引用。

签名密钥仅存进程内存,重启后全部旧 URL 失效(预期行为)。
SDK 的 custom_route 不经过 MCP 鉴权中间件,本层自行完成全部校验。
"""

from __future__ import annotations

import asyncio
import hmac
import mimetypes
import re
import secrets
import shutil
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote

import jwt
from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .errors import NOT_WHITELISTED, McpError, to_mcp_error

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from .tools.common import ServerState

CHUNK_SIZE = 1024 * 1024  # pyrogram stream_media 的分块上限(1 MiB)

_UID_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")
# 与 pyrogram stream_media 的媒体探测顺序一致
_MEDIA_ATTRS = ("audio", "document", "photo", "sticker", "animation", "video", "voice", "video_note")

# parse_range 的哨兵返回:区间无法满足(应回 416);None 表示忽略 Range(发全量)
UNSATISFIABLE: Final = "unsatisfiable"

_CLEANUP_INTERVAL = 600  # 过期上传目录的清理周期(秒)


def sanitize_name(name: str) -> str:
    """文件名净化:取 basename(兼容 / 与 \\)、去控制字符与前导 . / 空格、限长 200。

    "../../x.png" -> "x.png";空结果回退 "file"。
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(c for c in base if c.isprintable())
    base = base.lstrip(" .")[:200]
    return base or "file"


def parse_range(header: str | None, size: int) -> tuple[int, int] | str | None:
    """解析单区间 Range 头 -> (start, end) 闭区间字节范围。

    - (start, end):可满足的区间;
    - None:无头/多区间/无法解析/非法区间,按忽略处理(发全量 200);
    - UNSATISFIABLE:start >= size 或后缀长度为 0,应回 416。
    """
    if not header or size <= 0:
        return None
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not m:
        return None
    start_s, end_s = m.groups()
    if not start_s:
        if not end_s:
            return None
        n = int(end_s)  # 后缀区间 bytes=-N
        if n <= 0:
            return UNSATISFIABLE
        return (max(0, size - n), size - 1)
    start = int(start_s)
    if start >= size:
        return UNSATISFIABLE
    if not end_s:
        end = size - 1
    else:
        end = int(end_s)
        if end < start:
            return None
        end = min(end, size - 1)
    return (start, end)


def media_info(msg: Any, message_id: int) -> dict[str, Any] | None:
    """取消息中第一个可用媒体的元数据(探测顺序同 pyrogram stream_media);无媒体返回 None。"""
    media = None
    kind = ""
    for kind in _MEDIA_ATTRS:
        media = getattr(msg, kind, None)
        if media is not None:
            break
    if media is None:
        return None
    size = getattr(media, "file_size", None) or 0
    mime = getattr(media, "mime_type", None) or {
        "photo": "image/jpeg",
        "voice": "audio/ogg",
        "video_note": "video/mp4",
    }.get(kind, "application/octet-stream")
    name = sanitize_name(getattr(media, "file_name", None) or f"{message_id}{mimetypes.guess_extension(mime) or ''}")
    return {"media": media, "size": size, "mime_type": mime, "file_name": name}


def default_base_url(public_base_url: str | None, host: str | None, port: int) -> str:
    """签名 URL 的对外基址:优先 PUBLIC_BASE_URL(如 Cloudflare tunnel 域名),
    否则按监听地址推导(0.0.0.0/::/空 → 127.0.0.1)。

    刻意不读请求 Host 头:隧道/反代会把它改写成内部地址。
    """
    if public_base_url:
        return public_base_url.rstrip("/")
    h = (host or "").strip()
    if h in ("", "0.0.0.0", "::"):
        h = "127.0.0.1"
    if ":" in h and not h.startswith("["):
        h = f"[{h}]"
    return f"http://{h}:{port}"


def resolve_media_ref(src: Any, uploads_dir: Path | None) -> Any:
    """upload://<uid>/<name> 引用 -> uploads 目录下的真实文件路径;其他值原样返回。

    发送工具在任何扩展名推断之前调用;引用失效/不存在时抛 UPLOAD_NOT_FOUND。
    不依赖 Starlette,供 telegram/client.py 复用。
    """
    if not isinstance(src, str) or not src.startswith("upload://"):
        return src
    uid, sep, name = src.removeprefix("upload://").partition("/")
    if not sep or not _UID_RE.fullmatch(uid):
        raise McpError("UPLOAD_NOT_FOUND", f"upload:// 引用格式不合法: {src}")
    if not name or name != sanitize_name(name):
        raise McpError("UPLOAD_NOT_FOUND", f"upload:// 引用文件名不合法: {src}")
    path = uploads_dir / uid / name if uploads_dir is not None else None
    if path is None or not path.is_file():
        raise McpError(
            "UPLOAD_NOT_FOUND",
            f"上传文件不存在或已过期: {src};请重新用 create_upload_url 上传",
        )
    return str(path)


class _UploadTooLarge(Exception):
    """流式上传超过大小上限(无 Content-Length 时的兜底)。"""


class FileGateway:
    """签名 URL 文件网关:短时效 HS256 JWT 绑定 scope 与具体资源。

    下载 claims:{scope:"download", acc, chat, msg};上传 claims:{scope:"upload", uid, name, max}。
    配置 AUTH_TOKEN 时,Authorization: Bearer <AUTH_TOKEN> 为主 token(不绑定资源,
    仅接受 header 传递;query 里塞 AUTH_TOKEN 只会被判为无效 JWT)。
    """

    def __init__(
        self,
        *,
        auth_token: str | None,
        base_url: str,
        ttl: int,
        max_upload_bytes: int,
        uploads_dir: Path,
        retention_seconds: int,
    ) -> None:
        self.secret = secrets.token_bytes(32)
        self.auth_token = auth_token
        self.base_url = base_url.rstrip("/")
        self.ttl = ttl
        self.max_upload_bytes = max_upload_bytes
        self.uploads_dir = Path(uploads_dir)
        self.retention_seconds = retention_seconds
        self.used_upload_ids: set[str] = set()
        self.state: ServerState | None = None  # lifespan 注入

    # ---------- 签名 ----------

    def sign(self, claims: dict) -> str:
        """签发短时效 HS256 token(自动附加 iat/exp)。"""
        now = int(time.time())
        return jwt.encode({**claims, "iat": now, "exp": now + self.ttl}, self.secret, "HS256")

    def verify(self, token: str, scope: str) -> dict:
        """校验签名与 scope;过期/篡改/scope 不符一律抛 ValueError(调用方转成 401)。"""
        try:
            claims = jwt.decode(token, self.secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise ValueError(f"签名 token 无效或已过期: {exc}") from exc
        if claims.get("scope") != scope:
            raise ValueError("签名 token 的 scope 不匹配")
        return claims

    # ---------- 响应工具 ----------

    @staticmethod
    def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
        return JSONResponse({"error": code, "message": message}, status_code=status, headers=headers)

    def _mcp_error(self, exc: McpError) -> JSONResponse:
        """McpError -> HTTP:白名单拒绝 403,其余按资源不存在 404。"""
        status = 403 if exc.code == NOT_WHITELISTED else 404
        return self._error(status, exc.code, exc.message)

    def _authenticate(self, request: Request, scope: str) -> dict | JSONResponse:
        """请求鉴权 -> claims 字典;失败返回 401 JSONResponse。

        Authorization: Bearer <AUTH_TOKEN>(仅 header)命中主 token 时返回
        {"scope": scope, "master": True};否则取 Bearer header 或 ?token= 的 JWT 校验。
        """
        header_token: str | None = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            header_token = auth[7:].strip()
        if header_token and self.auth_token and hmac.compare_digest(header_token, self.auth_token):
            return {"scope": scope, "master": True}
        token = header_token or request.query_params.get("token")
        if not token:
            return self._error(401, "UNAUTHORIZED", "缺少访问 token(?token= 或 Authorization: Bearer)")
        try:
            return self.verify(token, scope)
        except ValueError as exc:
            return self._error(401, "UNAUTHORIZED", str(exc))

    # ---------- 路由 ----------

    def register_routes(self, mcp: MCPServer[Any]) -> None:
        """挂到 MCP 的 Starlette 应用;custom_route 不走 SDK 鉴权,校验全在本层。"""

        @mcp.custom_route("/files/{chat_id}/{message_id}", methods=["GET", "HEAD"])
        async def _files(request: Request) -> Response:
            return await self.download(request)

        @mcp.custom_route("/upload/{name}", methods=["PUT"])
        async def _upload(request: Request) -> Response:
            return await self.upload(request)

    # ---------- 下载 ----------

    async def download(self, request: Request) -> Response:
        """GET/HEAD /files/{chat_id}/{message_id}:签名 URL 或主 token 授权,流式回传媒体。"""
        state = self.state
        if state is None:
            return self._error(503, "UNAVAILABLE", "服务器未就绪(lifespan 未完成)")
        auth = self._authenticate(request, "download")
        if isinstance(auth, Response):
            return auth
        try:
            chat_id = int(str(request.path_params["chat_id"]))
            message_id = int(str(request.path_params["message_id"]))
        except (KeyError, ValueError):
            return self._error(401, "UNAUTHORIZED", "路径 chat_id/message_id 必须为数字")

        if auth.get("master"):
            # 主 token 不绑定资源:账号取 ?account= 或默认,仍走白名单
            account: str | None = request.query_params.get("account") or None
            try:
                client = state.resolve(account)
                from .tools.common import require_chat  # 延迟导入:files ↔ tools.common 循环依赖

                require_chat(state.resolve_access(account), chat_id)
            except McpError as exc:
                return self._mcp_error(exc)
        else:
            # 签名 token 绑定账号与具体消息,路径/参数必须与 claims 完全一致
            if auth.get("chat") != chat_id or auth.get("msg") != message_id:
                return self._error(401, "UNAUTHORIZED", "签名 URL 与该路径不匹配")
            account = str(auth.get("acc") or "")
            q = request.query_params.get("account")
            if q is not None and q != account:
                return self._error(401, "UNAUTHORIZED", "account 参数与签名不符")
            try:
                client = state.resolve(account)
            except McpError as exc:
                return self._mcp_error(exc)

        try:
            msg = await client.raw.get_messages(chat_id, message_id)
        except Exception as exc:  # noqa: BLE001 - RPC/网络错误统一按资源不可达处理
            return self._mcp_error(to_mcp_error(exc))
        info = media_info(msg, message_id)
        if msg is None or info is None:
            return self._error(404, "NO_MEDIA", f"消息 {message_id} 没有可下载媒体")

        size: int = info["size"]
        headers = {
            "Content-Type": str(info["mime_type"]),
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(str(info['file_name']), safe='')}",
        }
        status = 200
        offset = 0  # stream_media 起始块(1 MiB 一块)
        skip = 0  # 首块内需丢弃的前导字节
        left: int | None = None  # 剩余应发送字节数(None = 全量)
        if size > 0:
            headers["Accept-Ranges"] = "bytes"
            rng = parse_range(request.headers.get("range"), size)
            if isinstance(rng, str):  # UNSATISFIABLE 哨兵
                headers["Content-Range"] = f"bytes */{size}"
                return self._error(416, "RANGE_NOT_SATISFIABLE", "请求的区间超出文件大小", headers)
            if rng is not None:
                start, end = rng
                status = 206
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
                left = end - start + 1
                headers["Content-Length"] = str(left)
                offset = start // CHUNK_SIZE
                skip = start - offset * CHUNK_SIZE
            else:
                headers["Content-Length"] = str(size)

        if request.method == "HEAD":
            return Response(status_code=status, headers=headers)

        async def body() -> AsyncGenerator[bytes, None]:
            nonlocal skip
            remaining = left
            async for chunk in client.raw.stream_media(msg, offset=offset):
                if skip:
                    chunk = chunk[skip:]
                    skip = 0
                    if not chunk:
                        continue
                if remaining is not None:
                    if remaining <= 0:
                        break
                    if len(chunk) >= remaining:
                        yield chunk[:remaining]
                        return
                    remaining -= len(chunk)
                yield chunk

        return StreamingResponse(body(), status_code=status, headers=headers)

    # ---------- 上传 ----------

    async def upload(self, request: Request) -> Response:
        """PUT /upload/{name}:流式落盘 uploads/<uid>/<name>,返回 upload:// 引用。"""
        if self.state is None:
            return self._error(503, "UNAVAILABLE", "服务器未就绪(lifespan 未完成)")
        auth = self._authenticate(request, "upload")
        if isinstance(auth, Response):
            return auth

        name = sanitize_name(str(request.path_params.get("name") or ""))
        if auth.get("master"):
            uid = secrets.token_urlsafe(16)  # 主 token 无 uid claim:服务端现生成
            max_bytes = self.max_upload_bytes
        else:
            uid = str(auth.get("uid") or "")
            if name != auth.get("name"):
                return self._error(401, "UNAUTHORIZED", "签名 URL 与路径文件名不匹配")
            max_bytes = int(auth.get("max") or self.max_upload_bytes)
        if not _UID_RE.fullmatch(uid):
            return self._error(401, "UNAUTHORIZED", "上传 uid 不合法")
        if uid in self.used_upload_ids or (self.uploads_dir / uid).exists():
            return self._error(409, "UPLOAD_ID_REUSED", "该上传 URL 已被使用(单次有效)")
        self.used_upload_ids.add(uid)  # 先占位:单次语义,即便失败也不允许复用

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > max_bytes:
                    return self._error(413, "TOO_LARGE", f"文件超过大小上限 {max_bytes} 字节")
            except ValueError:
                pass  # 解析不了就靠流式计数兜底

        dest_dir = self.uploads_dir / uid
        part = dest_dir / f"{name}.part"
        final = dest_dir / name
        total = 0
        try:
            dest_dir.mkdir(parents=True)
            with part.open("wb") as f:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise _UploadTooLarge
                    f.write(chunk)
            part.replace(final)
        except _UploadTooLarge:
            shutil.rmtree(dest_dir, ignore_errors=True)
            return self._error(413, "TOO_LARGE", f"文件超过大小上限 {max_bytes} 字节")
        except Exception as exc:  # noqa: BLE001 - 落盘失败清理半成品目录
            logger.warning("上传落盘失败 uid={}: {}", uid, exc)
            shutil.rmtree(dest_dir, ignore_errors=True)
            return self._error(500, "UPLOAD_FAILED", f"上传保存失败: {exc}")
        return JSONResponse({"media": f"upload://{uid}/{name}", "size_bytes": total})

    # ---------- 过期清理 ----------

    async def cleanup_loop(self) -> None:
        """后台清理:启动即扫一遍,之后每 10 分钟扫一次过期上传目录。"""
        while True:
            try:
                self.cleanup_once()
            except Exception as exc:  # noqa: BLE001 - 清理失败不致命
                logger.debug("上传目录清理失败: {}", exc)
            await asyncio.sleep(_CLEANUP_INTERVAL)

    def cleanup_once(self) -> None:
        """删除 uploads_dir 下 mtime 早于 retention_seconds 的 uid 子目录。"""
        if not self.uploads_dir.is_dir():
            return
        cutoff = time.time() - self.retention_seconds
        for child in self.uploads_dir.iterdir():
            try:
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue
