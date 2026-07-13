"""开发围栏脚本测试。"""

from pathlib import Path

from scripts.check_architecture import check_file_size, check_forbidden_imports
from scripts.check_generated_artifacts import find_forbidden_paths


def test_forbidden_api_import_is_rejected(tmp_path: Path) -> None:
    """API 不得绕过应用服务直接调用每日流水线实现。"""
    source = tmp_path / "service.py"
    source.write_text("from runtime.daily_pipeline import run_production_daily_pipeline\n", encoding="utf-8")

    errors = check_forbidden_imports([source], ["runtime.daily_pipeline"], tmp_path)

    assert errors == ["service.py: 禁止依赖 runtime.daily_pipeline"]


def test_allowed_import_does_not_report_error(tmp_path: Path) -> None:
    """API 可以依赖标准 PipelineService。"""
    source = tmp_path / "service.py"
    source.write_text("from runtime.pipeline_service import PipelineService\n", encoding="utf-8")

    errors = check_forbidden_imports([source], ["runtime.daily_pipeline"], tmp_path)

    assert errors == []


def test_file_size_allowlist_only_exempts_known_debt(tmp_path: Path) -> None:
    """历史例外不应放宽新文件的500行限制。"""
    legacy = tmp_path / "legacy.py"
    new_file = tmp_path / "new_file.py"
    content = "value = 1\n" * 501
    legacy.write_text(content, encoding="utf-8")
    new_file.write_text(content, encoding="utf-8")

    errors = check_file_size(
        [legacy, new_file],
        max_lines=500,
        allowlist={"legacy.py": "历史债务"},
        root=tmp_path,
    )

    assert errors == ["new_file.py: 501 行，超过 500 行限制"]


def test_generated_artifact_paths_are_rejected() -> None:
    """每日运行产物和数据库不得进入 Git。"""
    tracked = [
        "runtime/pipeline_service.py",
        "runs/20260713/daily_report.md",
        "reports/dashboard_data.json",
        "data/live_market.duckdb",
    ]

    errors = find_forbidden_paths(
        tracked,
        generated_prefixes=["runs/", "reports/dashboard_data.json"],
    )

    assert errors == [
        "data/live_market.duckdb: 运行数据库不得提交",
        "reports/dashboard_data.json: 自动生成产物不得提交",
        "runs/20260713/daily_report.md: 自动生成产物不得提交",
    ]
