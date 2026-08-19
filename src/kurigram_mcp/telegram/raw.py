"""raw MTProto 调用编解码:函数解析、嵌套对象构造、结果序列化、接口发现。"""

from __future__ import annotations

import re

from pyrogram.raw import functions, types
from pyrogram.raw.core.tl_object import TLObject

from ..errors import INTERNAL, McpError

# 内部/握手类模块,对 AI 调试无意义,发现时跳过
_SKIP_MODULES = {
    "req_pq",
    "req_pq_multi",
    "req_dh_params",
    "set_client_dh_params",
    "destroy_auth_key",
    "destroy_session",
    "get_future_salts",
    "init_connection",
    "invoke_after_msg",
    "invoke_after_msgs",
    "invoke_with_apns_secret",
    "invoke_with_business_connection",
    "invoke_with_google_play_integrity",
    "invoke_with_layer",
    "invoke_with_messages_range",
    "invoke_with_re_captcha",
    "invoke_with_takeout",
    "invoke_without_updates",
    "ping",
    "ping_delay_disconnect",
    "rpc_drop_answer",
}


def camelize(name: str) -> str:
    """getHistory -> GetHistory;inputPeerUser -> InputPeerUser。"""
    return name[0].upper() + name[1:] if name else name


def resolve_function(path: str) -> type[TLObject]:
    """messages.getHistory -> pyrogram.raw.functions.messages.GetHistory。"""
    parts = path.strip().split(".")
    if len(parts) != 2 or not all(parts):
        raise McpError(
            INTERNAL, f"函数名格式应为 module.method(如 messages.getHistory),收到: {path!r}"
        )
    mod_name, cls_name = parts
    mod = getattr(functions, mod_name, None)
    if mod is None:
        raise McpError(INTERNAL, f"未知的 raw 函数模块: {mod_name}")
    cls = getattr(mod, camelize(cls_name), None)
    if cls is None or not (isinstance(cls, type) and issubclass(cls, TLObject)):
        raise McpError(INTERNAL, f"未知的 raw 函数: {path}")
    return cls


def parse_doc(cls: type[TLObject]) -> dict:
    """从生成代码的 docstring 解析参数类型与返回类型(生成文件标准格式)。"""
    doc = cls.__doc__ or ""
    params: list[dict] = []
    m = re.search(r"Parameters:\s*\n(.*?)(?=\n\s*Returns:|\Z)", doc, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            pm = re.match(r"(\w+)\s+\(([^)]+)\):?\s*(.*)", line.strip())
            if pm:
                params.append(
                    {
                        "name": pm.group(1),
                        "type": pm.group(2).strip(),
                        "description": pm.group(3).strip(),
                    }
                )
    returns_m = re.search(r"Returns:\s*\n\s*(.*)", doc)
    layer_m = re.search(r"Layer:\s*``(\d+)``", doc)
    id_m = re.search(r"ID:\s*``([0-9A-F]+)``", doc)
    return {
        "name": f"{_module_of(cls)}.{_snake_of(cls)}",
        "id_hex": f"0x{id_m.group(1).lower()}" if id_m else None,
        "layer": int(layer_m.group(1)) if layer_m else None,
        "params": params,
        "returns": returns_m.group(1).strip() if returns_m else None,
        "doc": doc.strip(),
    }


def _module_of(cls: type[TLObject]) -> str:
    """GetChats -> messages(通过 QUALNAME)。"""
    qual = getattr(cls, "QUALNAME", "")
    parts = qual.split(".")
    return parts[-2] if len(parts) >= 2 else ""


def _snake_of(cls: type[TLObject]) -> str:
    """GetChats -> getChats。"""
    name = cls.__name__
    return name[0].lower() + name[1:]


def _iter_functions():
    """迭代所有业务 raw 函数:(path, cls)。"""
    for mod_name in dir(functions):
        if mod_name.startswith("_"):
            continue
        mod = getattr(functions, mod_name)
        if isinstance(mod, type) and issubclass(mod, TLObject):
            # 顶层函数类(如 Ping)属于内部协议,跳过
            continue
        elif mod_name in _SKIP_MODULES or "_" in mod_name:
            continue
        else:
            for cls_name in dir(mod):
                if cls_name.startswith("_"):
                    continue
                cls = getattr(mod, cls_name)
                if isinstance(cls, type) and issubclass(cls, TLObject):
                    yield f"{mod_name}.{_snake_of(cls)}", cls


def list_functions(
    query: str | None = None, module: str | None = None, limit: int = 50
) -> list[dict]:
    """枚举 raw 函数清单(name + 参数名 + 一句话描述)。"""
    out: list[dict] = []
    q = (query or "").lower()
    for path, cls in _iter_functions():
        if q and q not in path.lower():
            continue
        if module and path.split(".")[0] != module.lower():
            continue
        info = parse_doc(cls)
        out.append(
            {
                "name": path,
                "id_hex": info["id_hex"],
                "params": [p["name"] for p in info["params"]],
                "returns": info["returns"],
            }
        )
        if len(out) >= limit:
            break
    return out


def get_function_info(path: str) -> dict:
    """单个 raw 函数的完整信息(参数名/类型/描述)。"""
    cls = resolve_function(path)
    info = parse_doc(cls)
    return info


def build_value(value):
    """把 JSON 值递归构造为 raw 对象:{"_": "inputPeerUser", ...} -> InputPeerUser(...)。"""
    if isinstance(value, dict):
        ctor = value.get("_")
        if ctor is None:
            return {k: build_value(v) for k, v in value.items()}
        cls = getattr(types, camelize(ctor), None)
        if cls is None or not (isinstance(cls, type) and issubclass(cls, TLObject)):
            raise McpError(INTERNAL, f"未知的 raw 类型: {ctor}")
        kwargs = {k: build_value(v) for k, v in value.items() if k != "_"}
        return cls(**kwargs)
    if isinstance(value, list):
        return [build_value(v) for v in value]
    return value


def to_plain(obj):
    """raw 对象/嵌套结构 -> JSON 安全结构(bytes 转 hex)。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, (list, tuple)):
        return [to_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, TLObject):
        out: dict = {"_": type(obj).__name__}
        for slot in getattr(type(obj), "__slots__", ()):
            if slot.startswith("_"):
                continue
            val = getattr(obj, slot, None)
            if val is None:
                continue
            out[slot] = to_plain(val)
        return out
    return str(obj)
