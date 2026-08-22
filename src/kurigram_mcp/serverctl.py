"""本地服务器只读探测:进程查找与端口检查。

服务器由 `km run` 前台运行(Ctrl-C 停止);本模块提供运行状态探测,
供 CLI 在线判断(`session add`)与改动生效提示使用。
基于 /proc 解析进程命令行(Linux/WSL),仅用标准库。
"""

from __future__ import annotations

import os
import socket


def server_process() -> tuple[int, list[str]] | None:
    """找到运行中的 kurigram-mcp run 进程,返回 (pid, 完整 cmdline)。"""
    me = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                parts = f.read().decode(errors="ignore").split("\0")[:-1]
        except OSError:
            continue
        if not parts:
            continue
        if ("kurigram_mcp" in parts or "kurigram-mcp" in parts) and "run" in parts:
            return int(pid), parts
    return None


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    """端口是否在监听。"""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0
