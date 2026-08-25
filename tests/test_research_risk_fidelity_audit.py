"""研究风险层历史审计测试。"""

from __future__ import annotations

from pathlib import Path

from examples.research_risk_fidelity_audit import (
    _classify_pending,
    _data_version,
    _experiment_id,
    render_report,
)
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_experiment_id_reads_static_strategy_id(tmp_path: Path) -> None:
    """审计不得导入研究模块，只读取静态实验ID。"""
    source = tmp_path / "sample_study.py"
    source.write_text(
        'STRATEGY_ID = "sample_v1"\nraise RuntimeError("不得导入")\n',
        encoding="utf-8",
    )

    assert _experiment_id(source) == "sample_v1"


def test_report_marks_pending_results_as_invalid_evidence() -> None:
    """待复验实验必须在报告中明确禁止用于晋级。"""
    result = {
        "as_of_date": "20260726",
        "affected_count": 2,
        "revalidated_count": 1,
        "pending_count": 1,
        "static_check_passed": True,
        "revalidated": [
            {
                "experiment_id": "done_v1",
                "latest_outcome": "REJECTED",
                "latest_run_id": "run-1",
            }
        ],
        "pending": [
            {
                "experiment_id": "pending_v1",
                "status": "needs_revalidation",
                "latest_outcome": "REJECTED",
            }
        ],
    }

    report = render_report(result)

    assert "pending_v1" in report
    assert "不能作为风险层有效性证据" in report
    assert "不得用待复验结果晋级生产策略" in report


def test_data_version_changes_with_source_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """源码修复必须改变审计数据版本。"""
    examples = tmp_path / "examples"
    scripts = tmp_path / "scripts"
    examples.mkdir()
    scripts.mkdir()
    names = {
        "pending.py",
        "done.py",
        "fixed.py",
    }
    for index, name in enumerate(sorted(names)):
        (examples / name).write_text(
            f'EXPERIMENT_ID = "sample_{index}"\nvalue = 1\n',
            encoding="utf-8",
        )
    checker = scripts / "check_research_risk_fidelity.py"
    checker.write_text("value = 1\n", encoding="utf-8")
    module = __import__(
        "examples.research_risk_fidelity_audit",
        fromlist=["unused"],
    )
    monkeypatch.setattr(module, "PENDING_MODULES", ("pending.py",))
    monkeypatch.setattr(module, "REVALIDATED_MODULES", ("done.py",))
    monkeypatch.setattr(module, "INTENTIONAL_FIXED_MODULES", ("fixed.py",))

    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    before = _data_version(paths)
    (examples / "pending.py").write_text(
        'EXPERIMENT_ID = "sample_2"\nvalue = 2\n',
        encoding="utf-8",
    )
    after = _data_version(paths)

    assert before != after


def test_revalidation_queue_converges_after_matching_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """成功运行当前定义后，实验必须自动移出待复验队列。"""
    examples = tmp_path / "examples"
    examples.mkdir()
    source = examples / "sample_study.py"
    source.write_text('STRATEGY_ID = "sample_v1"\n', encoding="utf-8")
    module = __import__(
        "examples.research_risk_fidelity_audit",
        fromlist=["unused"],
    )
    monkeypatch.setattr(module, "PENDING_MODULES", ("sample_study.py",))
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_experiment(
        {
            "experiment_id": "sample_v1",
            "name": "样例",
            "status": "active",
            "definition_fingerprint": "current",
        }
    )
    repository.record_experiment_run(
        experiment_id="sample_v1",
        run_id="run-1",
        run_date="20260726",
        status="SUCCESS",
        output_dir=tmp_path / "runs",
        definition_fingerprint="current",
        outcome="REJECTED",
    )

    pending, revalidated = _classify_pending(repository, tmp_path)

    assert pending == []
    assert revalidated[0]["experiment_id"] == "sample_v1"
    assert revalidated[0]["latest_run_id"] == "run-1"
