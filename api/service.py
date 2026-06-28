"""本地前端 API 查询服务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.strategy_catalog import register_quality_alpha_v1


class LocalApiService:
    """聚合系统状态库和监控库，给本地前端提供稳定 JSON 数据。"""

    def __init__(self, paths: RuntimePaths | None = None) -> None:
        self.paths = paths or get_runtime_paths()
        self.system_repository = SystemRepository(self.paths.system_state_path)
        register_quality_alpha_v1(self.system_repository)
        self.monitoring_repository = MonitoringRepository(self.paths.monitoring_path)

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

    def runs(self, strategy_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        """返回运行记录。"""
        return self.system_repository.list_runs(strategy_id=strategy_id, limit=limit)

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
