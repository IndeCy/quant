"""开发围栏脚本测试。"""

from pathlib import Path

from scripts.check_architecture import (
    check_file_size,
    check_forbidden_imports,
    check_research_attempt_guard,
)
from scripts.check_generated_artifacts import find_forbidden_paths, find_ignored_sources
from scripts.check_research_risk_fidelity import find_research_risk_errors


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


def test_source_files_cannot_be_silently_ignored() -> None:
    """宽泛的 lib 忽略规则不能再次吞掉前端源码。"""
    ignored = ["frontend/node_modules/lib.js", "frontend/src/shared/lib/formatters.ts", "runtime/__pycache__/x.pyc"]

    assert find_ignored_sources(ignored) == ["frontend/src/shared/lib/formatters.ts"]


def test_new_research_entrypoint_requires_dedup_guard(tmp_path: Path) -> None:
    """新增研究脚本若绕过研究指纹门禁，架构验收必须失败。"""
    examples = tmp_path / "examples"
    examples.mkdir()
    research = examples / "new_factor_study.py"
    research.write_text("def run():\n    return 1\n", encoding="utf-8")

    assert check_research_attempt_guard(tmp_path) == [
        "examples/new_factor_study.py: 耗时研究必须先通过 runtime.research_attempts 去重门禁"
    ]

    research.write_text(
        "from runtime.research_attempts import begin_research_attempt\n",
        encoding="utf-8",
    )
    assert check_research_attempt_guard(tmp_path) == []


def test_research_risk_overlay_requires_explicit_grid(tmp_path: Path) -> None:
    """有阈值的覆盖层必须显式进入研究指纹。"""
    examples = tmp_path / "examples"
    examples.mkdir()
    study = examples / "factor_study.py"
    study.write_text(
        'SPEC = {"risk_overlay": {"threshold": 0.45, '
        '"reduced_exposure": 0.3}}\n',
        encoding="utf-8",
    )

    errors = find_research_risk_errors(tmp_path)

    assert errors == [
        "examples/factor_study.py:1: 波动率风险层必须显式声明 "
        "scheme/mode=GRID"
    ]


def test_research_grid_declaration_cannot_call_fixed(tmp_path: Path) -> None:
    """声明GRID但执行FIXED时总验收必须失败。"""
    examples = tmp_path / "examples"
    examples.mkdir()
    study = examples / "factor_study.py"
    study.write_text(
        'SPEC = {"risk_overlay": {"scheme": "GRID", '
        '"threshold": 0.45, "reduced_exposure": 0.3}}\n'
        'run_risk_layer_backtest("x", "FIXED", {}, None)\n',
        encoding="utf-8",
    )

    assert find_research_risk_errors(tmp_path) == [
        "examples/factor_study.py: 声明 GRID 风险层但实际调用 FIXED"
    ]


def test_research_none_declaration_allows_fixed(tmp_path: Path) -> None:
    """明确无覆盖层的研究可以用FIXED表示满仓。"""
    examples = tmp_path / "examples"
    examples.mkdir()
    study = examples / "factor_study.py"
    study.write_text(
        'SPEC = {"risk_overlay": "none"}\n'
        'run_risk_layer_backtest("x", "FIXED", {}, None)\n',
        encoding="utf-8",
    )

    assert find_research_risk_errors(tmp_path) == []


def test_fixed_cannot_silently_ignore_grid_thresholds(tmp_path: Path) -> None:
    """即使没有声明，FIXED也不能吞掉波动率阈值参数。"""
    examples = tmp_path / "examples"
    examples.mkdir()
    study = examples / "factor_study.py"
    study.write_text(
        'run_risk_layer_backtest("x", "FIXED", {}, None, None, None, None, '
        'vol_threshold=0.45, reduced_exposure=0.3)\n',
        encoding="utf-8",
    )

    assert find_research_risk_errors(tmp_path) == [
        "examples/factor_study.py:1: FIXED 会忽略波动率阈值参数，应使用 GRID"
    ]


def test_ci_m0_approval_requires_scoped_pr_label() -> None:
    """CI 只能通过显式 PR 标签注入 M0 审批，不能永久关闭门禁。"""
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/guardrails.yml").read_text(encoding="utf-8")

    assert "types: [opened, synchronize, reopened, labeled, unlabeled]" in workflow
    assert "github.event_name == 'pull_request'" in workflow
    assert "contains(github.event.pull_request.labels.*.name, 'm0-approved')" in workflow
    assert "QUANT_APPROVE_M0_CHANGE: 1" not in workflow
    assert 'QUANT_APPROVE_M0_CHANGE: "1"' not in workflow
