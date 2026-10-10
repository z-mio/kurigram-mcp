"""FileGateway 签名 URL 上传/下载网关测试。

无 httpx 依赖:用一个最小 ASGI 驱动(手工 scope/receive/send)打 Starlette 应用。
"""

from __future__ import annotations

import json
import os
import time
import types
from pathlib import Path

import jwt
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from kurigram_mcp.errors import McpError
from kurigram_mcp.files import (
    CHUNK_SIZE,
    UNSATISFIABLE,
    FileGateway,
    parse_range,
    resolve_media_ref,
    sanitize_name,
)
from kurigram_mcp.tools.common import ServerState

CHAT_ID = -1001234567890
OTHER_CHAT_ID = -1009999999999  # 不在白名单
MSG_ID = 42
AUTH_TOKEN = "test-master-token"
# ≈2.5 MiB,跨两个 1 MiB 块边界
DATA = (bytes(range(256)) * (3 * CHUNK_SIZE // 256 + 1))[: 2 * CHUNK_SIZE + 12345]


# ---------- 伪对象 ----------


class FakeRaw:
    """伪 pyrogram Client:get_messages 返回带 document 的消息;stream_media 按 1 MiB 分块。"""

    def __init__(self, data: bytes = DATA) -> None:
        self._data = data

    async def get_messages(self, chat_id, message_id):
        if chat_id != CHAT_ID or message_id != MSG_ID:
            return types.SimpleNamespace()  # 无媒体
        doc = types.SimpleNamespace(
            file_id="file-id",
            file_size=len(self._data),
            mime_type="application/pdf",
            file_name="a.pdf",
        )
        return types.SimpleNamespace(document=doc)

    async def stream_media(self, msg, limit=0, offset=0):
        for start in range(offset * CHUNK_SIZE, len(self._data), CHUNK_SIZE):
            yield self._data[start : start + CHUNK_SIZE]


class FakeAccess:
    def __init__(self, allowed: set[int] | None = None) -> None:
        self._allowed = allowed if allowed is not None else {CHAT_ID}

    def is_allowed(self, chat_id: int) -> bool:
        return chat_id in self._allowed


class FakeClient:
    def __init__(self, data: bytes = DATA) -> None:
        self.raw = FakeRaw(data)
        self.settings = types.SimpleNamespace(account_name="default")


def make_state(gw: FileGateway | None = None) -> ServerState:
    state = ServerState(
        clients={"default": FakeClient()},  # type: ignore[dict-item]
        accesses={"default": FakeAccess()},  # type: ignore[dict-item]
        default="default",
    )
    if gw is not None:
        state.files = gw
    return state


def make_gateway(tmp_path: Path, auth_token: str | None = AUTH_TOKEN, **kw) -> FileGateway:
    gw = FileGateway(
        auth_token=auth_token,
        base_url="http://test.local:8765",
        ttl=600,
        max_upload_bytes=1024 * 1024,
        uploads_dir=tmp_path / "uploads",
        retention_seconds=3600,
        **kw,
    )
    gw.state = make_state(gw)
    return gw


def make_app(gw: FileGateway) -> Starlette:
    return Starlette(
        routes=[
            Route("/files/{chat_id}/{message_id}", gw.download, methods=["GET", "HEAD"]),
            Route("/upload/{name}", gw.upload, methods=["PUT"]),
        ]
    )


# ---------- 最小 ASGI 驱动 ----------


async def asgi_request(
    app, method: str, path: str, *, headers: dict | None = None, body: bytes = b"", chunk_size: int | None = None
) -> tuple[int, dict, bytes]:
    p, _, q = path.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.5"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": p,
        "raw_path": p.encode(),
        "query_string": q.encode(),
        "root_path": "",
        "headers": [(k.lower().encode(), str(v).encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }
    chunks = [body[i : i + chunk_size] for i in range(0, len(body), chunk_size)] if chunk_size else [body]
    idx = {"i": 0, "done": False}

    async def receive():
        if idx["i"] < len(chunks):
            chunk = chunks[idx["i"]]
            idx["i"] += 1
            return {"type": "http.request", "body": chunk, "more_body": idx["i"] < len(chunks)}
        idx["done"] = True
        return {"type": "http.disconnect"}

    messages = []

    async def send(msg):
        messages.append(msg)

    await app(scope, receive, send)
    status = 0
    resp_headers: dict = {}
    resp_body = b""
    for m in messages:
        if m["type"] == "http.response.start":
            status = m["status"]
            resp_headers = {k.decode(): v.decode() for k, v in m["headers"]}
        elif m["type"] == "http.response.body":
            resp_body += m.get("body", b"")
    return status, resp_headers, resp_body


def dl_token(gw: FileGateway, chat: int = CHAT_ID, msg: int = MSG_ID, acc: str = "default") -> str:
    return gw.sign({"scope": "download", "acc": acc, "chat": chat, "msg": msg})


def up_token(gw: FileGateway, uid: str, name: str, max_bytes: int = 1024 * 1024) -> str:
    return gw.sign({"scope": "upload", "uid": uid, "name": name, "max": max_bytes})


# ---------- 签名 ----------


def test_sign_verify_roundtrip(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    tok = gw.sign({"scope": "download", "chat": 1})
    claims = gw.verify(tok, "download")
    assert claims["chat"] == 1
    assert claims["exp"] - claims["iat"] == gw.ttl


def test_verify_rejects_bad_tokens(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    tok = gw.sign({"scope": "download"})
    with pytest.raises(ValueError):  # 过期
        expired = jwt.encode({"scope": "download", "iat": 1, "exp": 2}, gw.secret, algorithm="HS256")
        gw.verify(expired, "download")
    with pytest.raises(ValueError):  # scope 不符
        gw.verify(tok, "upload")
    with pytest.raises(ValueError):  # 篡改签名
        gw.verify(tok.rsplit(".", 1)[0] + ".forged", "download")


# ---------- Range 解析 ----------


def test_parse_range() -> None:
    size = len(DATA)
    assert parse_range("bytes=0-0", size) == (0, 0)
    assert parse_range("bytes=1048570-1048580", size) == (1048570, 1048580)  # 跨块边界
    assert parse_range("bytes=100-", size) == (100, size - 1)
    assert parse_range("bytes=-10", size) == (size - 10, size - 1)
    assert parse_range("bytes=0-1,3-4", size) is None  # 多区间 → 忽略
    assert parse_range("garbage", size) is None
    assert parse_range("bytes=99999999-", size) == UNSATISFIABLE
    assert parse_range("bytes=-0", size) == UNSATISFIABLE
    assert parse_range(None, size) is None
    assert parse_range("bytes=0-100", 0) is None  # size==0 忽略


# ---------- 下载 ----------


async def test_download_full(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    status, headers, body = await asgi_request(make_app(gw), "GET", f"/files/{CHAT_ID}/{MSG_ID}?token={dl_token(gw)}")
    assert status == 200
    assert body == DATA
    assert headers["content-length"] == str(len(DATA))
    assert headers["content-type"] == "application/pdf"
    assert headers["accept-ranges"] == "bytes"
    assert "a.pdf" in headers["content-disposition"]


async def test_download_range_cross_chunk(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    status, headers, body = await asgi_request(
        make_app(gw),
        "GET",
        f"/files/{CHAT_ID}/{MSG_ID}?token={dl_token(gw)}",
        headers={"Range": "bytes=1048570-1048580"},
    )
    assert status == 206
    assert body == DATA[1048570:1048581]
    assert headers["content-range"] == f"bytes 1048570-1048580/{len(DATA)}"
    assert headers["content-length"] == "11"


async def test_download_range_unsatisfiable(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    status, headers, _ = await asgi_request(
        make_app(gw),
        "GET",
        f"/files/{CHAT_ID}/{MSG_ID}?token={dl_token(gw)}",
        headers={"Range": f"bytes={len(DATA)}-"},
    )
    assert status == 416
    assert headers["content-range"] == f"bytes */{len(DATA)}"


async def test_download_auth_matrix(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    app = make_app(gw)

    # 无 token → 401
    status, _, _ = await asgi_request(app, "GET", f"/files/{CHAT_ID}/{MSG_ID}")
    assert status == 401

    # 绑定其他消息 id 的 token → 401
    status, _, _ = await asgi_request(app, "GET", f"/files/{CHAT_ID}/{MSG_ID}?token={dl_token(gw, msg=MSG_ID + 1)}")
    assert status == 401

    # ?account= 与 claims 不符 → 401
    status, _, _ = await asgi_request(app, "GET", f"/files/{CHAT_ID}/{MSG_ID}?token={dl_token(gw)}&account=other")
    assert status == 401

    # 主 AUTH_TOKEN(header)→ 200
    status, _, body = await asgi_request(
        app, "GET", f"/files/{CHAT_ID}/{MSG_ID}", headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
    )
    assert status == 200
    assert body == DATA

    # query 里塞 AUTH_TOKEN → 只是无效 JWT → 401
    status, _, _ = await asgi_request(app, "GET", f"/files/{CHAT_ID}/{MSG_ID}?token={AUTH_TOKEN}")
    assert status == 401

    # 主 token 仍走白名单:非白名单 chat → 403
    status, _, _ = await asgi_request(
        app, "GET", f"/files/{OTHER_CHAT_ID}/{MSG_ID}", headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
    )
    assert status == 403


async def test_download_head(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    status, headers, body = await asgi_request(make_app(gw), "HEAD", f"/files/{CHAT_ID}/{MSG_ID}?token={dl_token(gw)}")
    assert status == 200
    assert body == b""
    assert headers["content-length"] == str(len(DATA))
    assert headers["content-type"] == "application/pdf"
    assert headers["accept-ranges"] == "bytes"


async def test_download_jwt_via_bearer_header(tmp_path) -> None:
    """签名 JWT 也能从 Authorization: Bearer 传入(与 master 同等入口)。"""
    gw = make_gateway(tmp_path)
    status, _, body = await asgi_request(
        make_app(gw),
        "GET",
        f"/files/{CHAT_ID}/{MSG_ID}",
        headers={"Authorization": f"Bearer {dl_token(gw)}"},
    )
    assert status == 200
    assert body == DATA


# ---------- 上传 ----------


async def test_upload_signed(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    app = make_app(gw)
    uid = "u" * 16
    token = up_token(gw, uid, "a.bin")
    body = b"hello" * 100
    status, _, resp = await asgi_request(app, "PUT", f"/upload/a.bin?token={token}", body=body, chunk_size=128)
    assert status == 200
    payload = json.loads(resp)
    assert payload == {"media": f"upload://{uid}/a.bin", "size_bytes": len(body)}
    assert (gw.uploads_dir / uid / "a.bin").read_bytes() == body
    assert not (gw.uploads_dir / uid / "a.bin.part").exists()

    # 同一 token 复用 → 409(单次有效)
    status, _, _ = await asgi_request(app, "PUT", f"/upload/a.bin?token={token}", body=b"x")
    assert status == 409


async def test_upload_content_length_over_limit(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    token = up_token(gw, "v" * 16, "a.bin", max_bytes=10)
    status, _, _ = await asgi_request(
        make_app(gw),
        "PUT",
        f"/upload/a.bin?token={token}",
        headers={"Content-Length": "100"},
        body=b"x" * 100,
    )
    assert status == 413


async def test_upload_streamed_over_limit(tmp_path) -> None:
    """无 Content-Length 时靠流式计数兜底;超限删整个 uid 目录。"""
    gw = make_gateway(tmp_path)
    uid = "w" * 16
    token = up_token(gw, uid, "a.bin", max_bytes=1024)
    status, _, _ = await asgi_request(
        make_app(gw), "PUT", f"/upload/a.bin?token={token}", body=b"x" * 5000, chunk_size=512
    )
    assert status == 413
    assert not (gw.uploads_dir / uid).exists()


async def test_upload_name_mismatch(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    token = up_token(gw, "x" * 16, "a.bin")
    status, _, _ = await asgi_request(make_app(gw), "PUT", f"/upload/b.bin?token={token}", body=b"x")
    assert status == 401


async def test_upload_master_token(tmp_path) -> None:
    """主 token 上传:服务端现生成 uid,路径文件名生效。"""
    gw = make_gateway(tmp_path)
    status, _, resp = await asgi_request(
        make_app(gw),
        "PUT",
        "/upload/c.txt",
        headers={"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Length": "5"},
        body=b"abcde",
    )
    assert status == 200
    media = json.loads(resp)["media"]
    assert media.startswith("upload://") and media.endswith("/c.txt")
    uid = media.removeprefix("upload://").split("/")[0]
    assert (gw.uploads_dir / uid / "c.txt").read_bytes() == b"abcde"


async def test_upload_no_token(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    status, _, _ = await asgi_request(make_app(gw), "PUT", "/upload/a.bin", body=b"x")
    assert status == 401


def test_sanitize_name() -> None:
    assert sanitize_name("../../x.png") == "x.png"
    assert sanitize_name("..\\x") == "x"
    assert sanitize_name(".hidden") == "hidden"
    assert sanitize_name("  spaced.txt") == "spaced.txt"
    assert sanitize_name("") == "file"
    assert sanitize_name("a" * 300) == "a" * 200
    assert sanitize_name("dir/sub/f.txt") == "f.txt"
    assert sanitize_name("a\x00b.bin") == "ab.bin"


# ---------- resolve_media_ref ----------


def test_resolve_media_ref(tmp_path) -> None:
    uploads = tmp_path / "uploads"
    # 非 upload:// 原样透传
    assert resolve_media_ref("/tmp/x.png", uploads) == "/tmp/x.png"
    assert resolve_media_ref("https://a/b.png", uploads) == "https://a/b.png"
    assert resolve_media_ref("file-id-abc", uploads) == "file-id-abc"

    uid = "y" * 16
    d = uploads / uid
    d.mkdir(parents=True)
    f = d / "a.bin"
    f.write_bytes(b"data")
    assert resolve_media_ref(f"upload://{uid}/a.bin", uploads) == str(f)

    with pytest.raises(McpError) as ei:
        resolve_media_ref(f"upload://{uid}/missing.bin", uploads)
    assert ei.value.code == "UPLOAD_NOT_FOUND"
    with pytest.raises(McpError) as ei:
        resolve_media_ref("upload://bad!/a.bin", uploads)
    assert ei.value.code == "UPLOAD_NOT_FOUND"
    with pytest.raises(McpError) as ei:
        resolve_media_ref(f"upload://{uid}/../evil", uploads)
    assert ei.value.code == "UPLOAD_NOT_FOUND"


# ---------- client 层接入 ----------


class FakeSendRaw:
    def __init__(self) -> None:
        self.document_media: str | None = None
        self.group_media: list | None = None

    async def send_document(self, chat_id, media, caption="", parse_mode=None, reply_parameters=None):
        self.document_media = media
        return types.SimpleNamespace(id=1)

    async def send_media_group(self, chat_id, items, reply_parameters=None):
        self.group_media = [i.media for i in items]
        return [types.SimpleNamespace(id=1)]


def make_tg_client(tmp_path: Path):
    from kurigram_mcp.telegram.client import TelegramClient

    settings = types.SimpleNamespace(
        downloads_dir=tmp_path / "downloads",
        sessions_dir=tmp_path / "sessions",
        uploads_dir=tmp_path / "uploads",
    )
    client = TelegramClient.__new__(TelegramClient)  # 跳过 __init__
    client.settings = settings
    client._client = FakeSendRaw()
    return client


async def test_send_document_resolves_upload_ref(tmp_path) -> None:
    client = make_tg_client(tmp_path)
    uid = "z" * 16
    d = tmp_path / "uploads" / uid
    d.mkdir(parents=True)
    f = d / "a.bin"
    f.write_bytes(b"x")
    await client.send_document(1, f"upload://{uid}/a.bin")
    assert client._client.document_media == str(f)


async def test_send_media_group_resolves_upload_ref(tmp_path) -> None:
    client = make_tg_client(tmp_path)
    uid = "z" * 16
    d = tmp_path / "uploads" / uid
    d.mkdir(parents=True)
    f = d / "a.png"
    f.write_bytes(b"x")
    await client.send_media_group(1, [f"upload://{uid}/a.png", {"media": f"upload://{uid}/a.png", "type": "photo"}])
    assert client._client.group_media == [str(f), str(f)]


async def test_send_document_missing_upload_ref(tmp_path) -> None:
    client = make_tg_client(tmp_path)
    with pytest.raises(McpError) as ei:
        await client.send_document(1, f"upload://{'q' * 16}/gone.bin")
    assert ei.value.code == "UPLOAD_NOT_FOUND"


# ---------- 过期清理 ----------


def test_cleanup_removes_old_uploads(tmp_path) -> None:
    gw = make_gateway(tmp_path)
    old = gw.uploads_dir / ("o" * 16)
    fresh = gw.uploads_dir / ("f" * 16)
    for d in (old, fresh):
        d.mkdir(parents=True)
        (d / "a.bin").write_bytes(b"x")
    past = time.time() - 7200  # retention=3600s
    os.utime(old, (past, past))
    gw.cleanup_once()
    assert not old.exists()
    assert fresh.exists()


# ---------- 工具层 ----------


async def test_get_media_url_tool(tmp_path) -> None:
    from mcp.server.mcpserver import MCPServer

    from kurigram_mcp.tools import read as read_tools

    gw = make_gateway(tmp_path)
    mcp: MCPServer = MCPServer(name="t")
    read_tools.register(mcp)
    fn = mcp._tool_manager.get_tool("get_media_url").fn  # type: ignore[attr-defined]
    ctx = types.SimpleNamespace(request_context=types.SimpleNamespace(lifespan_context=gw.state))
    out = await fn(ctx, chat_id=CHAT_ID, message_id=MSG_ID)
    assert out["file_name"] == "a.pdf"
    assert out["mime_type"] == "application/pdf"
    assert out["size_bytes"] == len(DATA)
    assert out["expires_in"] == gw.ttl
    # 生成的 URL 可直接下载
    status, _, body = await asgi_request(make_app(gw), "GET", out["url"].replace("http://test.local:8765", ""))
    assert status == 200
    assert body == DATA


async def test_create_upload_url_tool(tmp_path) -> None:
    from mcp.server.mcpserver import MCPServer

    from kurigram_mcp.tools import chat as chat_tools

    gw = make_gateway(tmp_path)
    mcp: MCPServer = MCPServer(name="t")
    chat_tools.register(mcp)
    fn = mcp._tool_manager.get_tool("create_upload_url").fn  # type: ignore[attr-defined]
    ctx = types.SimpleNamespace(request_context=types.SimpleNamespace(lifespan_context=gw.state))
    out = await fn(ctx, file_name="report.pdf")
    uid = out["media"].removeprefix("upload://").split("/")[0]
    assert out["media"] == f"upload://{uid}/report.pdf"
    assert out["max_bytes"] == gw.max_upload_bytes
    assert out["expires_in"] == gw.ttl
    # 生成的 URL 可直接上传,upload:// 引用随后可解析
    status, _, resp = await asgi_request(
        make_app(gw), "PUT", out["url"].replace("http://test.local:8765", ""), body=b"pdf-bytes"
    )
    assert status == 200
    assert resolve_media_ref(out["media"], gw.uploads_dir) == str(gw.uploads_dir / uid / "report.pdf")


async def test_sdk_auth_middleware_passes_jwt_to_custom_route(tmp_path) -> None:
    """回归:配置 AUTH_TOKEN 时,custom_route 上的 Bearer JWT 不被 SDK 全局鉴权中间件拦截。

    SDK 只对 /mcp 路由套 RequireAuthMiddleware;AuthenticationMiddleware 对
    未知 token 只是标记未认证(不拦截),因此我们的处理器仍有机会自行校验。
    """
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.mcpserver import MCPServer
    from mcp.server.transport_security import TransportSecuritySettings

    from kurigram_mcp.server import StaticTokenVerifier

    gw = make_gateway(tmp_path)
    mcp = MCPServer(
        name="t",
        auth=AuthSettings(
            issuer_url="http://127.0.0.1",  # type: ignore[arg-type]
            resource_server_url="http://127.0.0.1",  # type: ignore[arg-type]
        ),
        token_verifier=StaticTokenVerifier(AUTH_TOKEN),
    )
    gw.register_routes(mcp)
    app = mcp.streamable_http_app(transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    status, _, body = await asgi_request(
        app,
        "GET",
        f"/files/{CHAT_ID}/{MSG_ID}",
        headers={"Authorization": f"Bearer {dl_token(gw)}"},
    )
    assert status == 200
    assert body == DATA


# ---------- --public-url ----------


def test_run_server_public_url_precedence(monkeypatch) -> None:
    """--public-url > settings.public_base_url > host:port 推导。"""
    import kurigram_mcp.server as srv
    from kurigram_mcp.config import Settings

    captured: dict = {}

    class StubMCP:
        def run(self, **kw):
            captured["run"] = kw

    def fake_build(settings, accounts=None, base_url=None):
        captured["base_url"] = base_url
        return StubMCP()

    monkeypatch.setattr(srv, "build_server", fake_build)
    srv.run_server(Settings(public_base_url="https://cfg.example.com"), public_url="https://cli.example.com")
    assert captured["base_url"] == "https://cli.example.com"
    srv.run_server(Settings(public_base_url="https://cfg.example.com"))
    assert captured["base_url"] == "https://cfg.example.com"
    srv.run_server(Settings(host="0.0.0.0", port=9000))
    assert captured["base_url"] == "http://127.0.0.1:9000"


def test_cli_public_url_flag() -> None:
    from kurigram_mcp.cli import build_parser

    args = build_parser().parse_args(["run", "--public-url", "https://x.example.com"])
    assert args.public_url == "https://x.example.com"


def test_cli_short_flags() -> None:
    from kurigram_mcp.cli import build_parser

    args = build_parser().parse_args(["run", "-a", "x", "-H", "0.0.0.0", "-p", "9000", "-u", "https://x", "-s"])
    assert args.account == "x"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.public_url == "https://x"
    assert args.stateful is True

    args = build_parser().parse_args(["session", "add", "n", "-x", "socks5://h:1", "-c", "1,2"])
    assert args.name == "n"
    assert args.proxy == "socks5://h:1"
    assert args.allowed_chat_ids == "1,2"

    args = build_parser().parse_args(["session", "set", "n", "-x", "", "-c", ""])
    assert args.proxy == ""
    assert args.allowed_chat_ids == ""


def test_cli_version_short_flag() -> None:
    from kurigram_mcp.cli import build_parser

    with pytest.raises(SystemExit) as ei:
        build_parser().parse_args(["-V"])
    assert ei.value.code == 0
