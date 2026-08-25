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
    def opportunity_concept_increment_path(self) -> Path:
        return self.data_dir / "opportunity_concept_increment.duckdb"

    @property
    def industry_increment_path(self) -> Path:
        return self.data_dir / "industry_increment.duckdb"

    @property
    def benchmark_increment_path(self) -> Path:
        return self.data_dir / "benchmark_increment.duckdb"

    @property
    def beta_increment_path(self) -> Path:
        return self.data_dir / "beta_increment.duckdb"

    @property
    def order_flow_path(self) -> Path:
        """定位个股订单规模资金流增量缓存。"""
        return self.data_dir / "order_flow_increment.duckdb"

    @property
    def top_inst_path(self) -> Path:
        """定位龙虎榜机构席位增量缓存。"""
        return self.data_dir / "top_inst_increment.duckdb"

    @property
    def base_market_path(self) -> Path:
        """定位只读历史行情基线，支持 Mac mini 通过配置无复制挂载。"""
        configured = get_config_value("QUANT_BASE_MARKET_DB", prefer_environ=True)
        if configured:
            return Path(configured).expanduser().resolve()
        filename = "daily_adj_19901219_20260615.duckdb"
        candidates = [
            self.root / filename,
            self.data_dir / filename,
            _project_root() / filename,
            _project_root().parent / "database" / filename,
        ]
        return next((candidate for candidate in candidates if candidate.exists()), candidates[0])

    def resolve_data_file(self, filename: str) -> Path:
        """在 QUANT_HOME 与项目根目录之间解析可迁移的只读数据文件。"""
        if not filename or Path(filename).name != filename:
            raise ValueError("filename must be a plain file name")
        candidates = [
            self.data_dir / filename,
            self.root / filename,
            _project_root() / "data" / filename,
            _project_root() / filename,
        ]
        return next((candidate for candidate in candidates if candidate.exists()), candidates[0])

    @property
    def fina_indicator_path(self) -> Path:
        return self.resolve_data_file("fina_indicator.duckdb")

    @property
    def income_statement_path(self) -> Path:
        return self.resolve_data_file("income.duckdb")

    @property
    def balance_sheet_path(self) -> Path:
        return self.resolve_data_file("balancesheet.duckdb")

    @property
    def cashflow_statement_path(self) -> Path:
        return self.resolve_data_file("cashflow.duckdb")

    @property
    def forecast_path(self) -> Path:
        """定位业绩预告历史库，研究与迁移统一通过运行路径解析。"""
        return self.resolve_data_file("forecast.duckdb")

    @property
    def dividend_path(self) -> Path:
        """定位标准分红增量库，避免研究脚本硬编码项目目录。"""
        return self.resolve_data_file("dividend_increment.duckdb")

    @property
    def earnings_express_path(self) -> Path:
        """定位业绩快报历史库。"""
        return self.resolve_data_file("express.duckdb")

    @property
    def shareholder_count_path(self) -> Path:
        """定位股东户数增量缓存。"""
        return self.data_dir / "shareholder_count_increment.duckdb"

    @property
    def holder_trade_path(self) -> Path:
        """定位重要股东增减持事件增量缓存。"""
        return self.data_dir / "holder_trade_increment.duckdb"

    @property
    def margin_trade_path(self) -> Path:
        """定位融资融券研究增量缓存，尚未纳入生产日更。"""
        return self.data_dir / "margin_trade_increment.duckdb"

    @property
    def block_trade_path(self) -> Path:
        """定位大宗交易事件增量缓存。"""
        return self.data_dir / "block_trade_increment.duckdb"

    @property
    def fund_ownership_path(self) -> Path:
        """定位公募基金披露持仓研究缓存。"""
        return self.data_dir / "fund_ownership_increment.duckdb"

    @property
    def fund_daily_history_path(self) -> Path:
        return self.resolve_data_file("etf_lof_reits_daily_adj_20041220_20260617.duckdb")

    @property
    def fund_basic_history_path(self) -> Path:
        return self.resolve_data_file("etf_lof_reits_basic_export_20041220_20260617.duckdb")

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
