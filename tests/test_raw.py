"""raw 编解码与错误映射测试。"""

from __future__ import annotations

import pytest

from kurigram_mcp.errors import FLOOD_WAIT, SESSION_INVALID, McpError, to_mcp_error
from kurigram_mcp.telegram.raw import build_value, camelize, resolve_function, to_plain


def test_camelize() -> None:
    assert camelize("getHistory") == "GetHistory"
    assert camelize("inputPeerUser") == "InputPeerUser"


def test_resolve_function_ok() -> None:
    cls = resolve_function("messages.getDialogs")
    assert cls.__name__ == "GetDialogs"
    assert resolve_function("account.getAccountTTL").__name__ == "GetAccountTTL"


def test_resolve_function_unknown() -> None:
    for bad in ("messages.nonexistent", "nope.method", "justone", "a.b.c"):
        with pytest.raises(McpError) as ei:
            resolve_function(bad)
        assert ei.value.code == "INTERNAL"


def test_build_value_nested_objects() -> None:
    built = build_value(
        {"offset_peer": {"_": "inputPeerEmpty"}, "limit": 3, "hash": 0, "tags": [1, "x"]}
    )
    assert built["offset_peer"].__class__.__name__ == "InputPeerEmpty"
    assert built["limit"] == 3
    assert built["tags"] == [1, "x"]


def test_build_value_unknown_type() -> None:
    with pytest.raises(McpError):
        build_value({"_": "bogus_type"})


def test_to_plain_objects_and_bytes() -> None:
    obj = build_value({"peer": {"_": "inputPeerUser", "user_id": 1, "access_hash": 2}})
    plain = to_plain(obj["peer"])
    assert plain["_"] == "InputPeerUser"
    assert plain["user_id"] == 1 and plain["access_hash"] == 2

    assert to_plain(b"\x01\x02") == "0102"
    assert to_plain([1, {"a": None}]) == [1, {"a": None}]
    assert to_plain(None) is None


def test_flood_wait_mapping() -> None:
    from pyrogram.errors import FloodWait

    err = to_mcp_error(FloodWait("A wait of 7 seconds is required"))
    assert err.code == FLOOD_WAIT
    assert err.details.get("seconds") == 7


def test_unauthorized_mapping() -> None:
    from pyrogram.errors import Unauthorized

    err = to_mcp_error(Unauthorized("SESSION_REVOKED"))
    assert err.code == SESSION_INVALID
    assert "auth" in err.message.lower()


def test_parse_doc_get_chats() -> None:
    """messages.getChats 的参数类型应为 List[int](官方 Vector<long>),不是对象。"""
    from pyrogram.raw.functions.messages import GetChats

    from kurigram_mcp.telegram.raw import parse_doc

    info = parse_doc(GetChats)
    assert info["name"] == "messages.getChats"
    assert info["id_hex"] == "0x49e9528f"
    assert any(p["name"] == "id" and "int" in p["type"] for p in info["params"]), info["params"]
    assert info["returns"] and "Chats" in info["returns"]


def test_list_functions_filter() -> None:
    from kurigram_mcp.telegram.raw import list_functions

    # 按 query 过滤
    hits = list_functions(query="getDialogs")
    assert any(m["name"] == "messages.getDialogs" for m in hits)

    # 按 module 过滤
    msgs = list_functions(module="messages", limit=10)
    assert all(m["name"].startswith("messages.") for m in msgs)
    assert len(msgs) <= 10

    # limit 生效
    assert len(list_functions(limit=5)) == 5


def test_get_function_info_full() -> None:
    from kurigram_mcp.telegram.raw import get_function_info

    info = get_function_info("messages.getDialogs")
    params = {p["name"]: p for p in info["params"]}
    assert "offset_peer" in params and "InputPeer" in params["offset_peer"]["type"]
    assert "limit" in params


def test_build_value_vector_long_mismatch_error() -> None:
    """给 Vector<long> 函数传对象,应得到可读的错误(而非晦涩 AttributeError)。"""
    from kurigram_mcp.telegram.raw import build_value

    # messages.getChats 的 id 期望 List[int];传 inputChannel 对象会序列化失败
    built = build_value({"id": [{"_": "inputChannel", "channel_id": 1, "access_hash": 2}]})
    from pyrogram.raw.functions.messages import GetChats

    func = GetChats(**built)
    try:
        func.write()
    except Exception as exc:  # noqa: BLE001
        assert "to_bytes" in str(exc)
    else:
        raise AssertionError("应序列化失败")
