"""统一 Pipeline 运行上下文。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4


TriggerType = Literal["SCHEDULED", "MANUAL", "API"]


@dataclass(frozen=True)
class PipelineContext:
    """跨调度、API 和命令行稳定传递的运行身份。"""

    run_id: str
    pipeline_id: str
    trade_date: str
    trigger_type: TriggerType
    code_version: str
    data_version: str
    started_at: str

    @classmethod
    def create(
        cls,
        pipeline_id: str,
        trade_date: str,
        trigger_type: TriggerType,
        code_version: str,
        data_version: str,
    ) -> "PipelineContext":
        """创建不可变运行上下文。"""
        return cls(
            run_id=uuid4().hex,
            pipeline_id=pipeline_id,
            trade_date=trade_date,
            trigger_type=trigger_type,
            code_version=code_version,
            data_version=data_version,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
