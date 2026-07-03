from pathlib import Path

from runtime.operations_ack import record_operations_ack
from runtime.operations_quality_report import build_operations_quality_report
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_operations_quality_report_writes_artifacts_and_registers_report(tmp_path: Path) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    record_operations_ack(
        paths.system_state_path,
        {
            "trade_date": "20260703",
            "source": "system_smoke",
            "category": "operations_ack",
            "name": "e19_smoke",
            "severity": "NORMAL",
            "decision": "NO_ACTION",
            "message": "smoke",
            "resolution": "ok",
            "operator": "codex",
        },
    )

    result = build_operations_quality_report(paths, {"status": "READY", "checks": []}, trade_date="20260703")

    markdown_path = Path(result["markdown_path"])
    json_path = Path(result["json_path"])
    assert markdown_path.exists()
    assert json_path.exists()
    assert "运维质量趋势" in markdown_path.read_text(encoding="utf-8")
    reports = SystemRepository(paths.system_state_path).list_reports("operations")
    assert reports[0]["report_type"] == "operations_quality_review"
