"""受保护变更检查测试。"""

from scripts.check_protected_changes import find_protected_changes, schema_change_without_migration


def test_m0_path_is_detected() -> None:
    """可信回测文件变化必须进入人工确认流程。"""
    changed = ["frontend/src/App.tsx", "backtest/execution_model.py"]

    assert find_protected_changes(changed, ["backtest/execution_model.py"]) == ["backtest/execution_model.py"]


def test_schema_change_requires_migration() -> None:
    """修改初始化 Schema 时必须同时新增 migration。"""
    assert schema_change_without_migration(["runtime/repository_schema.py"]) is True
    assert schema_change_without_migration(
        ["runtime/repository_schema.py", "runtime/migrations/003_add_orders.sql"]
    ) is False
