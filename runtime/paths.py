"""统一管理本地运行目录，降低迁移到常驻机器的成本。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runtime.config import get_config_value


def _project_root() -> Path:
    """从当前文件位置定位项目根目录，避免依赖启动命令所在目录。"""
    return Path(__file__).resolve().parents[1]


def _runtime_root() -> Path:
    """优先使用 QUANT_HOME；未配置时保持旧的项目目录落盘方式。"""
    value = get_config_value("QUANT_HOME", prefer_environ=True)
    return Path(value).expanduser().resolve() if value else _project_root()


@dataclass(frozen=True)
class RuntimePaths:
    """集中描述所有可变运行产物路径。

    历史基线库仍由研究脚本显式指定；这里仅接管每日运行会持续变化、
    后续迁移 Mac mini 时必须整体备份的文件。
    """

    root: Path

    @classmethod
    def from_environment(cls) -> "RuntimePaths":
        """按当前环境变量创建运行路径集合。"""
        return cls(root=_runtime_root())

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def live_market_increment_path(self) -> Path:
        return self.data_dir / "live_market_increment.duckdb"

    @property
    def limit_list_increment_path(self) -> Path:
        return self.data_dir / "limit_list_increment.duckdb"

    @property
    def benchmark_increment_path(self) -> Path:
        return self.data_dir / "benchmark_increment.duckdb"

    @property
    def quality_overlay_paper_path(self) -> Path:
        return self.data_dir / "quality_overlay_paper.sqlite3"

    @property
    def paper_trading_path(self) -> Path:
        return self.data_dir / "paper_trading.sqlite3"

    @property
    def factor_scores_path(self) -> Path:
        return self.data_dir / "factor_scores.sqlite3"

    @property
    def monitoring_path(self) -> Path:
        return self.data_dir / "monitoring.sqlite3"

    @property
    def system_state_path(self) -> Path:
        return self.state_dir / "quant_system.sqlite"

    @property
    def scheduler_state_path(self) -> Path:
        return self.state_dir / "scheduler.sqlite"

    @property
    def scheduler_heartbeat_path(self) -> Path:
        return self.state_dir / "scheduler.heartbeat"

    @property
    def latest_report_path(self) -> Path:
        return self.reports_dir / "quality_overlay_paper_latest.md"

    @property
    def dashboard_json_path(self) -> Path:
        return self.reports_dir / "dashboard_data.json"

    @property
    def dashboard_html_path(self) -> Path:
        return self.reports_dir / "dashboard.html"

    def ensure_directories(self) -> None:
        """创建运行系统需要的一级目录，具体数据库由各自模块初始化。"""
        for directory in [
            self.data_dir,
            self.state_dir,
            self.runs_dir,
            self.reports_dir,
            self.logs_dir,
            self.config_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)


def get_runtime_paths() -> RuntimePaths:
    """返回当前进程的运行目录配置。"""
    return RuntimePaths.from_environment()
