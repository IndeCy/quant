from pathlib import Path

from runtime.operations_ack import list_operations_ack, record_operations_ack


def test_record_operations_ack_persists_manual_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "system_state.sqlite"

    ack = record_operations_ack(
        db_path,
        {
            "trade_date": "20260703",
            "source": "readiness",
            "category": "scheduler",
            "name": "scheduler_job",
            "severity": "CRITICAL",
            "decision": "ACTION_REQUIRED",
            "message": "每日任务未登记",
            "resolution": "已重新登记调度",
            "operator": "admin",
        },
    )

    records = list_operations_ack(db_path)
    assert ack["ack_id"] == records[0]["ack_id"]
    assert records[0]["status"] == "ACKNOWLEDGED"
    assert records[0]["resolution"] == "已重新登记调度"


def test_record_operations_ack_rejects_missing_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "system_state.sqlite"

    try:
        record_operations_ack(db_path, {"trade_date": "20260703"})
    except ValueError as exc:
        assert "source, category and name are required" in str(exc)
    else:
        raise AssertionError("missing identity should fail")
