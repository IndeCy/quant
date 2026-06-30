"""本地前端 API 查询服务。"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from monitoring.mainline_adapter import sync_mainline_chain_monitoring
from monitoring.repository import MonitoringRepository
from runtime.backup import build_backup_manifest
from runtime.logs import list_log_files, read_log_file
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.readiness import build_readiness_report
from runtime.repository import SystemRepository
from runtime.scheduler import configure_daily_pipeline_job, load_scheduler_status
from runtime.service_manager import build_service_manifest, build_service_status
from runtime.strategy_instance_catalog import register_builtin_strategy_instances
from runtime.strategy_templates import list_strategy_templates
from runtime.strategy_catalog import register_builtin_strategies


class LocalApiService:
    """聚合系统状态库和监控库，给本地前端提供稳定 JSON 数据。"""

    def __init__(self, paths: RuntimePaths | None = None) -> None:
        self.paths = paths or get_runtime_paths()
        self.system_repository = SystemRepository(self.paths.system_state_path)
        register_builtin_strategies(self.system_repository)
        register_builtin_strategy_instances(self.system_repository)
        self.monitoring_repository = MonitoringRepository(self.paths.monitoring_path)
        sync_mainline_chain_monitoring(self.paths, self.monitoring_repository, self.system_repository)

    def health(self) -> dict[str, Any]:
        """返回运行目录和关键数据库是否存在。"""
        return {
            "status": "ok",
            "runtime_root": str(self.paths.root),
            "system_state_exists": self.paths.system_state_path.exists(),
            "monitoring_exists": self.paths.monitoring_path.exists(),
            "runs_dir": str(self.paths.runs_dir),
            "reports_dir": str(self.paths.reports_dir),
        }

    def scheduler_status(self) -> dict[str, Any]:
        """返回本地每日调度器状态。"""
        return _json_ready(load_scheduler_status(self.paths))

    def configure_scheduler_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        """登记本地每日调度任务，但不立即执行流水线。"""
        hour = int(payload.get("hour", 16))
        minute = int(payload.get("minute", 30))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("hour must be 0-23 and minute must be 0-59")
        return _json_ready(
            configure_daily_pipeline_job(
                self.paths,
                hour=hour,
                minute=minute,
                skip_update=bool(payload.get("skip_update", False)),
                push=bool(payload.get("push", False)),
            )
        )

    def backup_manifest(self) -> dict[str, Any]:
        """返回运行目录备份和迁移清单。"""
        return _json_ready(build_backup_manifest(self.paths))

    def service_manifest(self) -> dict[str, Any]:
        """返回本地常驻服务启动命令和 launchd 模板。"""
        return _json_ready(build_service_manifest(self.paths))

    def service_status(self) -> dict[str, Any]:
        """返回本地常驻服务巡检状态。"""
        return _json_ready(build_service_status(self.paths))

    def readiness(self) -> dict[str, Any]:
        """返回生产候选系统运行就绪度。"""
        return _json_ready(
            build_readiness_report(
                token_present=bool(os.getenv("TUSHARE_TOKEN", "").strip()),
                data_health=self.data_health(),
                scheduler_status=self.scheduler_status(),
                service_status=self.service_status(),
            )
        )

    def logs(self) -> list[dict[str, Any]]:
        """返回运行日志索引。"""
        return _json_ready(list_log_files(self.paths))

    def log_content(self, log_id: str) -> dict[str, Any] | None:
        """返回运行日志内容。"""
        return _json_ready(read_log_file(self.paths, log_id))

    def research_todos(self) -> dict[str, Any]:
        """返回项目研究待办资料库。"""
        path = Path(__file__).resolve().parents[1] / "docs" / "todos.md"
        if not path.exists():
            return {"title": "待办资料库", "path": str(path), "content": "", "missing": True}
        return {
            "title": "待办资料库",
            "path": str(path),
            "content": path.read_text(encoding="utf-8"),
            "missing": False,
        }

    def factor_ideas(self) -> list[dict[str, Any]]:
        """返回自然语言因子想法列表。"""
        return self.system_repository.list_factor_ideas()

    def save_factor_idea(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存外部因子想法，暂不要求已经可执行。"""
        return self.system_repository.upsert_factor_idea(payload)

    def strategy_ideas(self) -> list[dict[str, Any]]:
        """返回自然语言策略想法列表。"""
        return self.system_repository.list_strategy_ideas()

    def save_strategy_idea(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存外部策略想法，后续可结构化为策略实例。"""
        return self.system_repository.upsert_strategy_idea(payload)

    def strategy_templates(self) -> list[dict[str, object]]:
        """返回可实例化策略模板。"""
        return list_strategy_templates()

    def strategy_instances(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """返回策略实例列表。"""
        return self.system_repository.list_strategy_instances(enabled_only=enabled_only)

    def save_strategy_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存可运行策略实例配置。"""
        return self.system_repository.upsert_strategy_instance(payload)

    def strategies(self) -> list[dict[str, Any]]:
        """返回策略列表。"""
        return self.system_repository.list_strategies()

    def strategy_detail(self, strategy_id: str) -> dict[str, Any] | None:
        """返回策略定义、最新运行状态和最新指标。"""
        definition = self.system_repository.load_strategy_definition(strategy_id)
        if definition is None:
            return None
        definition["latest_run"] = self.system_repository.latest_run(strategy_id)
        definition["latest_metrics"] = self.monitoring_repository.load_latest_strategy_metrics(strategy_id)
        return _json_ready(definition)

    def factors(self) -> list[dict[str, Any]]:
        """返回因子列表。"""
        return self.system_repository.list_factors()

    def save_factor(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存正式因子定义，只登记元数据，不生成因子计算逻辑。"""
        factor_id = str(payload.get("factor_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not factor_id or not name:
            raise ValueError("factor_id and name are required")
        self.system_repository.upsert_factor(
            factor_id=factor_id,
            name=name,
            category=str(payload.get("category") or "custom"),
            direction=str(payload.get("direction") or "unknown"),
            source=str(payload.get("source") or "manual"),
            description=str(payload.get("description") or ""),
            config=dict(payload.get("config") or {}),
        )
        detail = self.system_repository.load_factor_definition(factor_id)
        if detail is None:
            raise RuntimeError("factor was not saved")
        return _json_ready(detail)

    def factor_detail(self, factor_id: str) -> dict[str, Any] | None:
        """返回因子定义和使用该因子的策略关系。"""
        definition = self.system_repository.load_factor_definition(factor_id)
        return _json_ready(definition) if definition else None

    def strategy_drafts(self) -> list[dict[str, Any]]:
        """返回本地策略草案列表。"""
        return self.system_repository.list_strategy_drafts()

    def strategy_draft_detail(self, draft_id: str) -> dict[str, Any] | None:
        """返回本地策略草案详情。"""
        definition = self.system_repository.load_strategy_draft(draft_id)
        return _json_ready(definition) if definition else None

    def save_strategy_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存本地策略草案，供前端维护因子组合。"""
        draft_id = str(payload.get("draft_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not draft_id or not name:
            raise ValueError("draft_id and name are required")
        factors = payload.get("factors") or []
        if not isinstance(factors, list) or not factors:
            raise ValueError("factors are required")
        self.system_repository.upsert_strategy_draft(
            draft_id=draft_id,
            name=name,
            description=str(payload.get("description") or ""),
            config=dict(payload.get("config") or {}),
            factors=factors,
        )
        detail = self.system_repository.load_strategy_draft(draft_id)
        if detail is None:
            raise RuntimeError("strategy draft was not saved")
        return _json_ready(detail)

    def reports(self, strategy_id: str | None = None) -> list[dict[str, Any]]:
        """返回报告索引。"""
        return self.system_repository.list_reports(strategy_id)

    def report_content(self, report_id: str) -> dict[str, Any] | None:
        """返回已登记报告的文本内容。"""
        report = self.system_repository.get_report(report_id)
        if report is None:
            return None
        path = Path(str(report["file_path"])).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return {**report, "content": "", "missing": True}
        return {**report, "content": path.read_text(encoding="utf-8"), "missing": False}

    def data_health(self) -> dict[str, Any]:
        """汇总本地数据文件的新鲜度。"""
        return {
            "runtime_root": str(self.paths.root),
            "live_market_increment": {
                "path": str(self.paths.live_market_increment_path),
                "exists": self.paths.live_market_increment_path.exists(),
                "latest_daily_date": _duckdb_max_date(self.paths.live_market_increment_path, "daily", "trade_date"),
                "latest_adj_factor_date": _duckdb_max_date(self.paths.live_market_increment_path, "adj_factor", "trade_date"),
            },
            "benchmark_increment": {
                "path": str(self.paths.benchmark_increment_path),
                "exists": self.paths.benchmark_increment_path.exists(),
                "latest_fund_date": _duckdb_max_date(self.paths.benchmark_increment_path, "fund_daily", "trade_date"),
                "latest_fund_adj_date": _duckdb_max_date(self.paths.benchmark_increment_path, "fund_adj", "trade_date"),
                "latest_index_date": _duckdb_max_date(self.paths.benchmark_increment_path, "index_daily", "trade_date"),
            },
            "monitoring": {
                "path": str(self.paths.monitoring_path),
                "exists": self.paths.monitoring_path.exists(),
                "latest_strategy_date": _sqlite_max_date(self.paths.monitoring_path, "strategy_nav_daily", "trade_date"),
                "latest_market_date": _sqlite_max_date(self.paths.monitoring_path, "market_state_daily", "trade_date"),
            },
            "system_state": {
                "path": str(self.paths.system_state_path),
                "exists": self.paths.system_state_path.exists(),
                "latest_run_date": _sqlite_max_date(self.paths.system_state_path, "strategy_runs", "trade_date"),
                "latest_report_date": _sqlite_max_date(self.paths.system_state_path, "report_index", "trade_date"),
            },
        }

    def runs(self, strategy_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        """返回运行记录。"""
        return self.system_repository.list_runs(strategy_id=strategy_id, limit=limit)

    def run_detail(self, strategy_id: str, trade_date: str) -> dict[str, Any] | None:
        """返回某次运行及其 pipeline 步骤。"""
        run = self.system_repository.get_run(strategy_id, trade_date)
        if run is None:
            return None
        return {
            "run": run,
            "steps": self.system_repository.list_run_steps(strategy_id, trade_date),
            "artifacts": self.system_repository.list_run_artifacts(strategy_id, trade_date),
        }

    def strategy_series(self, strategy_id: str) -> list[dict[str, Any]]:
        """返回策略净值、风险和执行成本曲线。"""
        frame = self.monitoring_repository.load_strategy_history(strategy_id)
        return _frame_records(frame)

    def market_series(self, benchmark_id: str) -> list[dict[str, Any]]:
        """返回大盘/基准观测曲线。"""
        frame = self.monitoring_repository.load_market_history(benchmark_id)
        return _frame_records(frame)


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame 转 JSON 友好 records。"""
    if frame.empty:
        return []
    return _json_ready(frame.to_dict(orient="records"))


def _duckdb_max_date(path: Path, table: str, column: str) -> str | None:
    """安全读取 DuckDB 表最大日期，文件或表不存在时返回空。"""
    if not path.exists():
        return None
    try:
        import duckdb

        with duckdb.connect(str(path), read_only=True) as con:
            value = con.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
    except Exception:
        return None
    return str(value) if value else None


def _sqlite_max_date(path: Path, table: str, column: str) -> str | None:
    """安全读取 SQLite 表最大日期，文件或表不存在时返回空。"""
    if not path.exists():
        return None
    try:
        with sqlite3.connect(path) as con:
            value = con.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
    except Exception:
        return None
    return str(value) if value else None


def _json_ready(value: Any) -> Any:
    """递归转换 pandas/numpy/Path 类型，保证 HTTP JSON 可序列化。"""
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return value
