"""Tushare 个股行为数据的权限、字段与历史覆盖前沿审计。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any, Callable, Protocol

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime.config import get_config_value
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "tushare_behavior_data_frontier_v1"
REPORT_PATH = Path("docs/research/tushare-behavior-data-frontier-v1.md")
PROBE_DATES = ("20150630", "20190131", "20230131", "20260724")
SOURCE_PRIORITY = ("hk_hold", "top_inst", "moneyflow")
EXPECTED_COLUMNS = {
    "hk_hold": {"trade_date", "ts_code", "ratio"},
    "top_inst": {"trade_date", "ts_code", "buy", "sell", "net_buy"},
    "moneyflow": {
        "trade_date",
        "ts_code",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
    },
}
MIN_NONEMPTY_DATES = {
    "hk_hold": 3,
    "top_inst": 3,
    "moneyflow": 4,
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Tushare个股行为数据前沿审计 V1",
    category="data_feasibility",
    hypothesis="现有Tushare权限能否提供区别于OHLCV和财报的点时个股行为数据",
    definition={
        "probe_dates": list(PROBE_DATES),
        "sources": {
            "hk_hold": {
                "mechanism": "northbound_stock_ownership_change",
                "priority": 1,
                "required_nonempty_dates": MIN_NONEMPTY_DATES["hk_hold"],
            },
            "top_inst": {
                "mechanism": "institutional_seat_net_buying",
                "priority": 2,
                "required_nonempty_dates": MIN_NONEMPTY_DATES["top_inst"],
            },
            "moneyflow": {
                "mechanism": "large_order_net_flow",
                "priority": 3,
                "required_nonempty_dates": MIN_NONEMPTY_DATES["moneyflow"],
            },
        },
        "selection": (
            "fixed_priority_then_access_then_expected_columns_then_history_coverage"
        ),
        "data_retention": "metadata_only_no_raw_rows",
        "decision": "source_feasibility_only_no_backtest",
        "methodology_version": "v1",
    },
)


class BehaviorProbeClient(Protocol):
    """声明前沿审计使用的三类 Tushare 接口。"""

    def hk_hold(self, trade_date: str) -> pd.DataFrame:
        """读取北向个股持仓。"""

    def top_inst(self, trade_date: str) -> pd.DataFrame:
        """读取龙虎榜机构席位。"""

    def moneyflow(self, trade_date: str) -> pd.DataFrame:
        """读取个股大单资金流。"""


class TushareBehaviorProbeClient:
    """真实 Tushare 探针，不在对象中暴露 Token。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def hk_hold(self, trade_date: str) -> pd.DataFrame:
        """读取北向个股持仓快照。"""
        return self._pro.hk_hold(trade_date=trade_date)

    def top_inst(self, trade_date: str) -> pd.DataFrame:
        """读取龙虎榜机构席位明细。"""
        return self._pro.top_inst(trade_date=trade_date)

    def moneyflow(self, trade_date: str) -> pd.DataFrame:
        """读取个股订单规模资金流。"""
        return self._pro.moneyflow(trade_date=trade_date)


@dataclass(frozen=True)
class ProbeRecord:
    """一次接口探针的非敏感元数据。"""

    source: str
    trade_date: str
    status: str
    row_count: int
    columns: tuple[str, ...]
    error: str = ""


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client_factory: Callable[[], BehaviorProbeClient] | None = None,
) -> dict[str, Any]:
    """先登记指纹，再执行少量跨年份权限探针。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, client_factory)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    client_factory: Callable[[], BehaviorProbeClient] | None,
) -> dict[str, Any]:
    """调用探针并按预先优先级选择后续候选。"""
    if client_factory is None:
        token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
        client: BehaviorProbeClient = TushareBehaviorProbeClient(token)
    else:
        client = client_factory()
    records = probe_sources(client)
    summaries = summarize_sources(records)
    selected = select_candidate(summaries)
    decision = (
        "CONTINUE_WITH_SELECTED_SOURCE"
        if selected is not None
        else "NO_USABLE_BEHAVIOR_SOURCE"
    )
    result = {
        "probe_dates": list(PROBE_DATES),
        "source_summaries": summaries,
        "selected_source": selected,
        "decision": decision,
        "raw_rows_persisted": False,
        "records": [record.__dict__ for record in records],
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def probe_sources(client: BehaviorProbeClient) -> list[ProbeRecord]:
    """依次探测固定来源和日期，错误被降为可审计结果。"""
    records: list[ProbeRecord] = []
    for source in SOURCE_PRIORITY:
        method = getattr(client, source)
        for trade_date in PROBE_DATES:
            try:
                frame = method(trade_date)
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError("接口未返回DataFrame")
                records.append(
                    ProbeRecord(
                        source=source,
                        trade_date=trade_date,
                        status="OK" if not frame.empty else "EMPTY",
                        row_count=int(len(frame)),
                        columns=tuple(sorted(map(str, frame.columns))),
                    )
                )
            except Exception as error:
                records.append(
                    ProbeRecord(
                        source=source,
                        trade_date=trade_date,
                        status="ERROR",
                        row_count=0,
                        columns=(),
                        error=_safe_error(error),
                    )
                )
    return records


def summarize_sources(
    records: list[ProbeRecord],
) -> dict[str, dict[str, Any]]:
    """汇总权限、字段和跨时期非空覆盖。"""
    summaries: dict[str, dict[str, Any]] = {}
    for source in SOURCE_PRIORITY:
        subset = [record for record in records if record.source == source]
        observed_columns = {
            column for record in subset for column in record.columns
        }
        expected = EXPECTED_COLUMNS[source]
        access_dates = sum(record.status != "ERROR" for record in subset)
        nonempty_dates = sum(record.status == "OK" for record in subset)
        errors = sorted(
            {record.error for record in subset if record.error}
        )
        summaries[source] = {
            "access_dates": access_dates,
            "nonempty_dates": nonempty_dates,
            "total_rows": sum(record.row_count for record in subset),
            "expected_columns_present": expected.issubset(observed_columns),
            "missing_columns": sorted(expected - observed_columns),
            "observed_columns": sorted(observed_columns),
            "errors": errors,
            "usable": (
                access_dates == len(PROBE_DATES)
                and nonempty_dates >= MIN_NONEMPTY_DATES[source]
                and expected.issubset(observed_columns)
            ),
        }
    return summaries


def select_candidate(
    summaries: dict[str, dict[str, Any]],
) -> str | None:
    """只按冻结优先级选择首个可用来源。"""
    return next(
        (
            source
            for source in SOURCE_PRIORITY
            if bool(summaries[source]["usable"])
        ),
        None,
    )


def render_report(result: dict[str, Any]) -> str:
    """生成人类可读的数据前沿报告。"""
    rows = "\n".join(
        f"| {source} | {summary['access_dates']}/{len(PROBE_DATES)} | "
        f"{summary['nonempty_dates']}/{len(PROBE_DATES)} | "
        f"{summary['total_rows']} | "
        f"{'是' if summary['expected_columns_present'] else '否'} | "
        f"{'PASS' if summary['usable'] else 'FAIL'} |"
        for source, summary in result["source_summaries"].items()
    )
    errors = "\n".join(
        f"- {source}：{'；'.join(summary['errors'])}"
        for source, summary in result["source_summaries"].items()
        if summary["errors"]
    )
    return f"""# Tushare 个股行为数据前沿审计 V1

- 探针日期：{', '.join(result['probe_dates'])}。
- 固定优先级：北向个股持仓、龙虎榜机构席位、个股大单资金流。
- 本阶段只保存权限、行数和字段元数据，不保存原始业务记录。

| 来源 | 可访问日期 | 非空日期 | 样本行数 | 必要字段 | 结论 |
|---|---:|---:|---:|---|---|
{rows}

## 接口错误

{errors or '- 无'}

## 结论

- 决策：`{result['decision']}`
- 入选来源：`{result['selected_source'] or '无'}`
- 本阶段没有执行全量回补、收益回测或生产注册。
"""


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档数据源选择及非敏感探针明细。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    records_path = attempt.output_dir / "probe_records.csv"
    pd.DataFrame(result.pop("records")).to_csv(records_path, index=False)
    selected = result["selected_source"]
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="CANDIDATE_SELECTED" if selected else "REJECTED",
        decision_reason=(
            f"按冻结优先级选择 {selected} 进入独立数据可行性"
            if selected
            else "现有权限下没有满足历史覆盖和字段要求的个股行为来源"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "行为数据前沿报告"),
            ExperimentArtifact("probe_records", records_path, "接口探针元数据"),
        ],
    )


def _safe_error(error: Exception) -> str:
    """压缩外部错误，避免保存请求参数或敏感信息。"""
    message = " ".join(str(error).split())
    return f"{type(error).__name__}: {message[:180]}"


def _data_version() -> str:
    """绑定客户端版本，不把 Token 写入研究指纹。"""
    import tushare

    return f"tushare:{tushare.__version__}:probe_v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
