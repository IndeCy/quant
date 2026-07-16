"""Mac mini 迁移后的运行目录完整性验收。"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from runtime.config import default_config_path
from runtime.paths import RuntimePaths


def audit_runtime_restore(
    paths: RuntimePaths,
    config_path: Path | None = None,
    frontend_dist_path: Path | None = None,
) -> dict[str, Any]:
    """检查目录、核心数据库、私密配置和静态前端是否可用。"""
    checks: list[dict[str, str]] = []
    for name in ["data", "state", "runs", "reports", "config", "logs"]:
        _append_exists_check(checks, f"directory:{name}", paths.root / name, expected_directory=True)
    _append_exists_check(checks, "local_config", config_path or default_config_path())
    _append_database_check(checks, "system_state", paths.system_state_path, "sqlite")
    _append_database_check(checks, "monitoring", paths.monitoring_path, "sqlite")
    _append_database_check(checks, "paper_trading", paths.paper_trading_path, "sqlite")
    _append_database_check(checks, "live_market_increment", paths.live_market_increment_path, "duckdb")
    _append_database_check(checks, "benchmark_increment", paths.benchmark_increment_path, "duckdb")
    _append_database_check(checks, "base_market", paths.base_market_path, "duckdb")
    _append_exists_check(
        checks,
        "frontend_dist",
        frontend_dist_path or Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html",
    )
    failed_count = sum(item["status"] == "FAIL" for item in checks)
    return {
        "status": "READY" if failed_count == 0 else "NOT_READY",
        "runtime_root": str(paths.root),
        "failed_count": failed_count,
        "checks": checks,
    }


def _append_exists_check(
    checks: list[dict[str, str]],
    name: str,
    path: Path,
    *,
    expected_directory: bool = False,
) -> None:
    """追加文件或目录存在性检查。"""
    exists = path.is_dir() if expected_directory else path.is_file()
    checks.append(
        {
            "name": name,
            "status": "PASS" if exists else "FAIL",
            "message": str(path) if exists else f"缺失: {path}",
        }
    )


def _append_database_check(
    checks: list[dict[str, str]],
    name: str,
    path: Path,
    database_type: str,
) -> None:
    """打开数据库做最小完整性检查，避免只验证文件存在。"""
    if not path.is_file():
        checks.append({"name": name, "status": "FAIL", "message": f"缺失: {path}"})
        return
    try:
        if database_type == "sqlite":
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
                result = con.execute("PRAGMA integrity_check").fetchone()
                if result is None or str(result[0]).lower() != "ok":
                    raise RuntimeError(f"integrity_check={result}")
        else:
            import duckdb

            with duckdb.connect(str(path), read_only=True) as con:
                con.execute("SELECT COUNT(*) FROM information_schema.tables").fetchone()
    except Exception as exc:
        checks.append({"name": name, "status": "FAIL", "message": f"无法读取 {path}: {exc}"})
        return
    checks.append({"name": name, "status": "PASS", "message": str(path)})
