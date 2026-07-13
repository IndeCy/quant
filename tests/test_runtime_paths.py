"""运行目录解析测试。"""

from pathlib import Path

from runtime.paths import RuntimePaths, get_runtime_paths


def test_runtime_paths_default_to_project_root(monkeypatch) -> None:
    """未配置 QUANT_HOME 时保持旧项目目录，避免破坏现有脚本。"""
    monkeypatch.delenv("QUANT_HOME", raising=False)

    paths = get_runtime_paths()

    assert paths.root == Path(__file__).resolve().parents[1]
    assert paths.live_market_increment_path == paths.root / "data" / "live_market_increment.duckdb"
    assert paths.runs_dir == paths.root / "runs"
    assert paths.dashboard_html_path == paths.root / "reports" / "dashboard.html"


def test_runtime_paths_use_quant_home(monkeypatch, tmp_path: Path) -> None:
    """配置 QUANT_HOME 后，所有可变产物集中到运行目录。"""
    runtime_home = tmp_path / "quant_runtime"
    monkeypatch.setenv("QUANT_HOME", str(runtime_home))

    paths = get_runtime_paths()

    assert paths.root == runtime_home.resolve()
    assert paths.live_market_increment_path == runtime_home / "data" / "live_market_increment.duckdb"
    assert paths.benchmark_increment_path == runtime_home / "data" / "benchmark_increment.duckdb"
    assert paths.beta_increment_path == runtime_home / "data" / "beta_increment.duckdb"
    assert paths.quality_overlay_paper_path == runtime_home / "data" / "quality_overlay_paper.sqlite3"
    assert paths.monitoring_path == runtime_home / "data" / "monitoring.sqlite3"
    assert paths.system_state_path == runtime_home / "state" / "quant_system.sqlite"
    assert paths.scheduler_state_path == runtime_home / "state" / "scheduler.sqlite"
    assert paths.latest_report_path == runtime_home / "reports" / "quality_overlay_paper_latest.md"


def test_runtime_paths_can_create_standard_directories(tmp_path: Path) -> None:
    """迁移目录初始化只创建标准一级目录，不写入业务数据。"""
    paths = RuntimePaths(tmp_path / "runtime")

    paths.ensure_directories()

    assert paths.data_dir.is_dir()
    assert paths.state_dir.is_dir()
    assert paths.runs_dir.is_dir()
    assert paths.reports_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.config_dir.is_dir()
