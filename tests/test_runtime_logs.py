"""运行日志索引测试。"""

from pathlib import Path

from runtime.logs import list_log_files, read_log_file
from runtime.paths import RuntimePaths


def test_list_log_files_indexes_service_and_run_logs(tmp_path: Path) -> None:
    """日志索引应覆盖服务日志和每日流水线日志。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    (paths.logs_dir / "api.log").write_text("api ok\n", encoding="utf-8")
    run_dir = paths.runs_dir / "20260626"
    run_dir.mkdir(parents=True)
    (run_dir / "run_log.txt").write_text("daily ok\n", encoding="utf-8")

    logs = list_log_files(paths)

    assert [item["log_type"] for item in logs] == ["run", "service"]
    assert logs[0]["name"] == "20260626/run_log.txt"
    assert logs[1]["name"] == "api.log"


def test_read_log_file_only_reads_indexed_runtime_logs(tmp_path: Path) -> None:
    """日志读取只能读取运行目录内已索引日志。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    log_path = paths.logs_dir / "api.log"
    log_path.write_text("api ok\n", encoding="utf-8")
    indexed = list_log_files(paths)[0]

    content = read_log_file(paths, indexed["log_id"])

    assert content is not None
    assert content["content"] == "api ok\n"
    assert read_log_file(paths, "missing") is None
