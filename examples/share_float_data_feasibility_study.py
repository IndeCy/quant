"""限售股解禁供给压力因子的点时数据可行性审计。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
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


EXPERIMENT_ID = "share_float_data_feasibility_v1"
REPORT_PATH = Path("docs/research/share-float-data-feasibility-v1.md")
ROW_LIMIT = 6_000
MIN_NONEMPTY_WINDOWS = 3
MIN_VALID_RATIO_SHARE = 0.95
MIN_KNOWN_BEFORE_EVENT_SHARE = 0.95
PROBE_WINDOWS = (
    ("20150101", "20150131"),
    ("20190101", "20190131"),
    ("20230101", "20230131"),
    ("20260701", "20260724"),
)
REQUIRED_COLUMNS = {
    "ts_code",
    "ann_date",
    "float_date",
    "float_share",
    "float_ratio",
    "holder_name",
    "share_type",
}
IDENTITY_COLUMNS = (
    "ts_code",
    "float_date",
    "holder_name",
    "share_type",
    "float_share",
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="限售股解禁供给压力数据可行性 V1",
    category="data_feasibility",
    hypothesis="未来解禁供给压力能否由公告日可见的解禁计划稳定重建",
    definition={
        "source": {"provider": "tushare", "endpoint": "share_float"},
        "probe_windows_by_float_date": [list(item) for item in PROBE_WINDOWS],
        "required_columns": sorted(REQUIRED_COLUMNS),
        "event_identity": list(IDENTITY_COLUMNS),
        "gates": {
            "all_windows_accessible": True,
            "minimum_nonempty_windows": MIN_NONEMPTY_WINDOWS,
            "row_count_must_be_below_api_limit": ROW_LIMIT,
            "valid_positive_float_ratio_share": MIN_VALID_RATIO_SHARE,
            "announced_no_later_than_float_date_share": (
                MIN_KNOWN_BEFORE_EVENT_SHARE
            ),
            "exact_duplicate_rows": 0,
            "same_identity_announcement_conflicts": 0,
        },
        "factor_direction_if_feasible": "lower_upcoming_float_ratio_is_better",
        "factor_horizon_calendar_days": 60,
        "decision": "fail_before_backtest_if_any_data_gate_fails",
        "methodology_version": "v1",
    },
)


class ShareFloatClient(Protocol):
    """声明 Tushare 解禁计划接口。"""

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        """按解禁日期区间读取计划。"""


class TushareShareFloatClient:
    """真实 Tushare 解禁计划客户端。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        """调用官方 share_float 接口。"""
        return self._pro.share_float(
            start_date=start_date,
            end_date=end_date,
        )


@dataclass(frozen=True)
class WindowProbe:
    """一次解禁窗口探针的非敏感结果。"""

    start_date: str
    end_date: str
    status: str
    row_count: int
    symbol_count: int
    error: str = ""


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client_factory: Callable[[], ShareFloatClient] | None = None,
) -> dict[str, Any]:
    """先登记研究指纹，再访问外部接口。"""
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
    client_factory: Callable[[], ShareFloatClient] | None,
) -> dict[str, Any]:
    """检查历史覆盖、截断和点时公告语义。"""
    client = _build_client(client_factory)
    probes: list[WindowProbe] = []
    frames: list[pd.DataFrame] = []
    observed_columns: set[str] = set()
    for start_date, end_date in PROBE_WINDOWS:
        try:
            frame = client.fetch(start_date, end_date)
            if not isinstance(frame, pd.DataFrame):
                raise TypeError("接口未返回DataFrame")
            frame = frame.copy()
            frame["_probe_start"] = start_date
            frames.append(frame)
            observed_columns.update(map(str, frame.columns))
            probes.append(
                WindowProbe(
                    start_date,
                    end_date,
                    "OK" if not frame.empty else "EMPTY",
                    int(len(frame)),
                    _symbol_count(frame),
                )
            )
        except Exception as error:
            probes.append(
                WindowProbe(
                    start_date,
                    end_date,
                    "ERROR",
                    0,
                    0,
                    _safe_error(error),
                )
            )
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    diagnostics = diagnose_semantics(combined)
    checks = {
        "all_windows_accessible": all(item.status != "ERROR" for item in probes),
        "cross_period_coverage": (
            sum(item.status == "OK" for item in probes) >= MIN_NONEMPTY_WINDOWS
        ),
        "required_columns_present": REQUIRED_COLUMNS.issubset(observed_columns),
        "no_window_hits_row_limit": all(
            item.row_count < ROW_LIMIT for item in probes
        ),
        "valid_float_ratio": (
            diagnostics["valid_positive_float_ratio_share"]
            >= MIN_VALID_RATIO_SHARE
        ),
        "known_before_event": (
            diagnostics["known_before_event_share"]
            >= MIN_KNOWN_BEFORE_EVENT_SHARE
        ),
        "event_identity_reconstructible": (
            diagnostics["exact_duplicate_rows"] == 0
            and diagnostics["same_identity_announcement_conflicts"] == 0
        ),
    }
    passed = all(checks.values())
    result = {
        "probe_windows": [asdict(item) for item in probes],
        "rows": int(len(combined)),
        "symbols": _symbol_count(combined),
        "missing_columns": sorted(REQUIRED_COLUMNS - observed_columns),
        "diagnostics": diagnostics,
        "checks": checks,
        "passed": passed,
        "decision": (
            "ELIGIBLE_FOR_FACTOR_DESIGN"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
        "raw_rows_persisted": False,
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def diagnose_semantics(frame: pd.DataFrame) -> dict[str, int | float]:
    """审计事件值、公告领先期和可去重性。"""
    if frame.empty or not REQUIRED_COLUMNS.issubset(frame.columns):
        return {
            "valid_positive_float_ratio_share": 0.0,
            "known_before_event_share": 0.0,
            "lead_days_median": 0.0,
            "exact_duplicate_rows": 0,
            "same_identity_announcement_conflicts": 0,
        }
    data = frame.copy()
    data["ann_date"] = pd.to_datetime(data["ann_date"], errors="coerce")
    data["float_date"] = pd.to_datetime(data["float_date"], errors="coerce")
    data["float_ratio"] = pd.to_numeric(data["float_ratio"], errors="coerce")
    lead_days = (data["float_date"] - data["ann_date"]).dt.days
    valid_ratio = data["float_ratio"].gt(0) & data["float_ratio"].le(100)
    known_before = lead_days.ge(0)
    group_columns = [*IDENTITY_COLUMNS, "ann_date"]
    conflicts = (
        data.groupby(group_columns, dropna=False)["float_ratio"]
        .nunique(dropna=False)
        .gt(1)
    )
    return {
        "valid_positive_float_ratio_share": float(valid_ratio.mean()),
        "known_before_event_share": float(known_before.mean()),
        "lead_days_median": float(lead_days.dropna().median()),
        "exact_duplicate_rows": int(
            data.drop(columns=["_probe_start"], errors="ignore").duplicated().sum()
        ),
        "same_identity_announcement_conflicts": int(conflicts.sum()),
    }


def render_report(result: dict[str, Any]) -> str:
    """生成解禁数据可行性报告。"""
    probes = "\n".join(
        f"| {item['start_date']}~{item['end_date']} | {item['status']} | "
        f"{item['row_count']} | {item['symbol_count']} | "
        f"{item['error'] or '-'} |"
        for item in result["probe_windows"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    diagnostics = result["diagnostics"]
    return f"""# 限售股解禁供给压力数据可行性 V1

本实验只检查数据，不读取收益或执行回测。

| 解禁窗口 | 状态 | 行数 | 股票数 | 错误 |
|---|---|---:|---:|---|
{probes}

## 数据语义

- 总记录：{result['rows']}，覆盖股票：{result['symbols']}。
- 缺失必要字段：{', '.join(result['missing_columns']) or '无'}。
- 有效正数解禁比例占比：
  {diagnostics['valid_positive_float_ratio_share']:.2%}。
- 公告不晚于解禁日占比：{diagnostics['known_before_event_share']:.2%}。
- 公告领先天数中位数：{diagnostics['lead_days_median']:.0f} 天。
- 完全重复记录：{diagnostics['exact_duplicate_rows']}。
- 同事件同公告日比例冲突：
  {diagnostics['same_identity_announcement_conflicts']}。

## 可信门禁

{checks}

## 结论

- 决策：`{result['decision']}`。
- 原始业务记录未落盘。
- 只有全部门禁通过后，才允许另行冻结“未来60天解禁比例越低越好”的因子；
  当前结果不包含任何收益判断。
"""


def _build_client(
    client_factory: Callable[[], ShareFloatClient] | None,
) -> ShareFloatClient:
    """构造真实或测试客户端。"""
    if client_factory is not None:
        return client_factory()
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
    return TushareShareFloatClient(token)


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """持久化报告及研究结论。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    probes_path = attempt.output_dir / "probe_windows.csv"
    pd.DataFrame(result["probe_windows"]).to_csv(probes_path, index=False)
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="FEASIBLE" if result["passed"] else "REJECTED",
        decision_reason=(
            "解禁计划点时数据门禁通过，可另行冻结因子"
            if result["passed"]
            else "解禁计划未通过冻结的数据门禁，未进入回测"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "解禁数据可行性报告"),
            ExperimentArtifact("probe_windows", probes_path, "窗口探针元数据"),
        ],
    )


def _symbol_count(frame: pd.DataFrame) -> int:
    """安全统计股票数量。"""
    if frame.empty or "ts_code" not in frame:
        return 0
    return int(frame["ts_code"].nunique())


def _safe_error(error: Exception) -> str:
    """压缩接口错误并避免泄露配置。"""
    message = " ".join(str(error).split())
    return f"{type(error).__name__}: {message[:180]}"


def _data_version() -> str:
    """绑定 SDK 版本和探针口径。"""
    import tushare

    return f"tushare:{tushare.__version__}:share_float_probe_v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
