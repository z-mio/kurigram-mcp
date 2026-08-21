"""TelegramClient 路径解析测试(2.2.25 download 行为适配)。"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from kurigram_mcp.telegram.client import TelegramClient


class FakeRaw:
    """伪 pyrogram Client:记录 download_media 调用并落盘。"""

    def __init__(self) -> None:
        self.calls = []
        self._media = types.SimpleNamespace()

    async def get_messages(self, chat_id, message_id):
        return types.SimpleNamespace(media=self._media)

    async def download_media(self, msg, file_name=None):
        self.calls.append(file_name)
        # 模拟 pyrogram 返回落盘路径(真实创建文件供 stat)
        p = Path(file_name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return str(p)


def make_client(tmp_path) -> TelegramClient:
    settings = types.SimpleNamespace(
        downloads_dir=tmp_path / "downloads",
        sessions_dir=tmp_path / "sessions",
    )
    client = TelegramClient.__new__(TelegramClient)  # 跳过 __init__
    client.settings = settings
    client._client = types.SimpleNamespace()  # 让 raw 属性可用
    return client


@pytest.mark.asyncio
async def test_download_media_default_path(tmp_path) -> None:
    client = make_client(tmp_path)
    raw = FakeRaw()
    client._client.download_media = raw.download_media
    client._client.get_messages = raw.get_messages
    out = await client.download_media(-1001, 7)
    assert raw.calls == [str(tmp_path / "downloads" / "-1001" / "7")]
    assert out["path"].endswith("7")


@pytest.mark.asyncio
async def test_download_media_relative_path_resolved_to_downloads(tmp_path) -> None:
    """相对路径以 downloads_dir 为基准,而不是落进 sessions/(2.2.25 行为)。"""
    client = make_client(tmp_path)
    raw = FakeRaw()
    client._client.download_media = raw.download_media
    client._client.get_messages = raw.get_messages
    await client.download_media(-1001, 7, path="media/x.png")
    assert raw.calls == [str(tmp_path / "downloads" / "media" / "x.png")]


@pytest.mark.asyncio
async def test_download_media_absolute_path_kept(tmp_path) -> None:
    client = make_client(tmp_path)
    raw = FakeRaw()
    client._client.download_media = raw.download_media
    client._client.get_messages = raw.get_messages
    target = tmp_path / "custom" / "y.png"
    await client.download_media(-1001, 7, path=str(target))
    assert raw.calls == [str(target)]
