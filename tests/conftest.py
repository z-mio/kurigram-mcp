"""测试隔离:把 KURIGRAM_MCP_HOME 指到临时目录,避免读到真实用户配置。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_config_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("KURIGRAM_MCP_HOME", str(tmp_path / "dshome"))
