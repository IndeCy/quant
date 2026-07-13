"""统一 PipelineService 测试。"""

from pathlib import Path
import sqlite3

import pytest

from runtime.paths import RuntimePaths
from runtime.pipeline_service import PipelineAlreadyRunningError, PipelineService
from runtime.pipeline_run_repository import PipelineRunRepository


def test_pipeline_service_records_versions_and_artifacts(tmp_path: Path) -> None:
    """统一入口必须记录可追溯元数据和每日产物。"""
    paths = RuntimePaths(tmp_path)

    def executor(**kwargs: object) -> dict[str, object]:
        run_dir = paths.runs_dir / str(kwargs["trade_date"])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "daily_report.md").write_text("ok", encoding="utf-8")
        return {"status": "SUCCESS", "trade_date": kwargs["trade_date"]}

    service = PipelineService(paths=paths, executor=executor)
    result = service.run("daily_trading_pipeline", "20260713", "MANUAL")

    assert result["status"] == "SUCCESS"
    assert result["run_id"]
    run = PipelineRunRepository(paths.system_state_path).latest("daily_trading_pipeline", "20260713")
    assert run is not None
    assert run["status"] == "SUCCESS"
    assert run["trigger_type"] == "MANUAL"
    assert run["code_version"]
    assert run["data_version"]
    with sqlite3.connect(paths.system_state_path) as con:
        artifacts = con.execute("SELECT artifact_type, file_path FROM run_artifacts WHERE run_id = ?", [run["run_id"]]).fetchall()
    assert artifacts == [("daily_report", str(paths.runs_dir / "20260713" / "daily_report.md"))]


def test_successful_pipeline_is_idempotent_unless_forced(tmp_path: Path) -> None:
    """同一交易日成功后默认不重复执行，明确 force 才允许补跑。"""
    calls: list[str] = []

    def executor(**kwargs: object) -> dict[str, object]:
        calls.append(str(kwargs["trade_date"]))
        return {"status": "SUCCESS"}

    service = PipelineService(paths=RuntimePaths(tmp_path), executor=executor)
    first = service.run("daily_trading_pipeline", "20260713", "SCHEDULED")
    skipped = service.run("daily_trading_pipeline", "20260713", "MANUAL")
    forced = service.run("daily_trading_pipeline", "20260713", "MANUAL", force=True)

    assert first["status"] == "SUCCESS"
    assert skipped["status"] == "SKIPPED"
    assert skipped["run_id"] == first["run_id"]
    assert forced["status"] == "SUCCESS"
    assert len(calls) == 2


def test_pipeline_failure_is_recorded_and_raised(tmp_path: Path) -> None:
    """业务失败必须保留失败记录，不能被包装成成功。"""
    def executor(**_: object) -> dict[str, object]:
        raise RuntimeError("data update failed")

    paths = RuntimePaths(tmp_path)
    service = PipelineService(paths=paths, executor=executor)

    with pytest.raises(RuntimeError, match="data update failed"):
        service.run("daily_trading_pipeline", "20260713", "API")

    run = PipelineRunRepository(paths.system_state_path).latest("daily_trading_pipeline", "20260713")
    assert run is not None
    assert run["status"] == "FAILED"
    assert "data update failed" in run["message"]


def test_pipeline_lock_prevents_parallel_execution(tmp_path: Path) -> None:
    """同一 Pipeline 和交易日不能并发执行。"""
    service = PipelineService(paths=RuntimePaths(tmp_path), executor=lambda **_: {"status": "SUCCESS"})

    with service.lock_manager.acquire("daily_trading_pipeline", "20260713"):
        with pytest.raises(PipelineAlreadyRunningError):
            service.run("daily_trading_pipeline", "20260713", "MANUAL", force=True)
