"""运行目录备份清单测试。"""

from pathlib import Path

from runtime.backup import build_backup_manifest
from runtime.paths import RuntimePaths


def test_build_backup_manifest_lists_migratable_runtime_paths(tmp_path: Path) -> None:
    """备份清单应覆盖迁移 Mac mini 时需要保留的运行数据。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    paths.live_market_increment_path.write_text("duckdb-placeholder", encoding="utf-8")
    paths.system_state_path.write_text("sqlite-placeholder", encoding="utf-8")

    manifest = build_backup_manifest(paths)

    names = [item["name"] for item in manifest["items"]]
    assert names == ["data", "state", "runs", "reports", "config", "logs"]
    assert manifest["runtime_root"] == str(paths.root)
    assert manifest["items"][0]["exists"] is True
    assert manifest["items"][0]["file_count"] >= 1
    assert manifest["backup_command"].startswith("tar -czf quant_runtime_backup_")
    assert "-C" in manifest["backup_command"]
