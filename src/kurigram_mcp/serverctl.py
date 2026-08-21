"""本地服务器进程管理:查找 / 重启 / 探测(供 CLI 与 setup 使用)。

基于 /proc 解析进程命令行(Linux/WSL),不引入 psutil 依赖。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger


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


def run_args_from_cmdline(parts: list[str]) -> list[str]:
    """提取 run 之后的参数(--port/--host/--path 等),供重启复用。"""
    try:
        idx = parts.index("run")
    except ValueError:
        return []
    return parts[idx + 1 :]


def spawn_server(args: list[str] | None = None) -> None:
    """以独立会话启动服务器(继承当前配置;args 为 run 的附加参数)。"""
    log_path = Path(os.environ.get("KURIGRAM_MCP_LOG", "/tmp/kurigram-server.log"))
    log = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - 进程生命周期内保持打开
    subprocess.Popen(
        [sys.executable, "-m", "kurigram_mcp", "run", *(args or [])],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    """端口是否在监听。"""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def stop_server(pid: int, timeout: float = 8.0) -> bool:
    """SIGTERM 优雅停止;超时强杀。返回是否已退出。"""
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.2)
    logger.warning("进程 {} 未在 {}s 内退出,强制结束", pid, timeout)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return False


def restart_server(settings) -> bool:
    """重启运行中的服务器;返回是否成功(端口就绪)。"""
    found = server_process()
    if found is None:
        logger.error("没有找到运行中的服务器;请直接 `km run`")
        return False
    pid, parts = found
    args = run_args_from_cmdline(parts)

    port = settings.port
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                pass

    logger.info("停止服务器 (pid={})...", pid)
    stop_server(pid)
    time.sleep(0.5)
    spawn_server(args)

    deadline = time.time() + 20
    while time.time() < deadline:
        if port_open(port):
            logger.success("服务器已重启: http://127.0.0.1:{}/mcp", port)
            return True
        time.sleep(0.5)
    logger.error("服务器启动后端口 {} 未就绪,请查看日志", port)
    return False
