"""静态前端服务器测试。"""

from pathlib import Path

import pytest

from runtime.static_frontend_server import resolve_static_target, serve_frontend


def test_static_frontend_server_falls_back_for_spa_routes(tmp_path: Path) -> None:
    """浏览器直接打开策略页时应返回入口文件。"""
    (tmp_path / "index.html").write_text("index", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("app", encoding="utf-8")

    assert resolve_static_target(tmp_path, "/strategies") == "index.html"
    assert resolve_static_target(tmp_path, "/assets/app.js") == "assets/app.js"
    assert resolve_static_target(tmp_path, "/api/health") == "api/health"


def test_static_frontend_server_requires_built_assets(tmp_path: Path) -> None:
    """未构建前端时必须明确失败，不能静默启动空服务。"""
    with pytest.raises(FileNotFoundError, match="npm run build:pre"):
        serve_frontend(tmp_path)
