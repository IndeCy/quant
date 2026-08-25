"""Paper执行SLA查询服务。"""

from __future__ import annotations

from typing import Any

from runtime.paper_execution_sla_repository import PaperExecutionSlaRepository
from runtime.paths import RuntimePaths
from runtime.strategy_paper_observation import StrategyPaperObservationRepository


class PaperExecutionSlaApiMixin:
    """为本地API提供只读SLA进度查询。"""

    paths: RuntimePaths

    def paper_execution_sla(self) -> dict[str, Any]:
        """返回Paper T+1执行准入进度和最近观察记录。"""
        repository = PaperExecutionSlaRepository(self.paths.system_state_path)
        strategy_repository = StrategyPaperObservationRepository(
            self.paths.system_state_path
        )
        strategies = []
        for instance in self.system_repository.list_strategy_instances(
            enabled_only=True
        ):
            config = dict(instance.get("config") or {})
            required_days = int(config.get("paper_observation_gate_days", 0))
            if required_days <= 0:
                continue
            strategy_id = str(instance["strategy_id"])
            strategies.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": str(instance["name"]),
                    "progress": strategy_repository.progress(
                        strategy_id,
                        required_days=required_days,
                    ),
                    "history": strategy_repository.history(strategy_id, limit=30),
                }
            )
        return {
            "progress": repository.progress(required_days=20),
            "history": repository.history(limit=30),
            "strategies": strategies,
        }
