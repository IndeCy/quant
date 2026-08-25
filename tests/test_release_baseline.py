"""发布基线和运行数据备份测试。"""

from pathlib import Path
import json
import subprocess
import sys
import tarfile

from runtime.paths import RuntimePaths
from runtime.release_baseline import create_release_baseline


def test_create_release_baseline_archives_runtime_and_manifest(tmp_path: Path) -> None:
    """发布基线应生成 runtime 备份包、manifest 和恢复说明。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    paths.system_state_path.write_text("state", encoding="utf-8")
    paths.logs_dir.joinpath("api.log").write_text("ok", encoding="utf-8")

    result = create_release_baseline(paths=paths, output_dir=tmp_path / "backups", label="smoke")

    assert Path(result["archive_path"]).exists()
    assert Path(result["manifest_path"]).exists()
    assert Path(result["restore_guide_path"]).exists()
    assert result["included_dirs"] == ["data", "state", "runs", "reports", "config", "logs"]
    with tarfile.open(result["archive_path"], "r:gz") as archive:
        names = archive.getnames()
    assert f"runtime/state/{paths.system_state_path.name}" in names
    assert "runtime/logs/api.log" in names


def test_create_release_baseline_cli_outputs_manifest(tmp_path: Path) -> None:
    """CLI 应输出 JSON，并在指定目录生成发布基线产物。"""
    script = Path(__file__).resolve().parents[1] / "scripts" / "create_release_baseline.py"

    output = subprocess.check_output(
        [
            sys.executable,
            str(script),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--output-dir",
            str(tmp_path / "backups"),
            "--label",
            "cli_smoke",
        ],
        text=True,
    )

    result = json.loads(output)
    assert result["label"] == "cli_smoke"
    assert Path(result["archive_path"]).exists()
    assert Path(result["manifest_path"]).exists()
