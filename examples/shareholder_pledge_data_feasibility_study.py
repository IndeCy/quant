"""股东质押治理风险因子的点时数据可行性审计。"""

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


EXPERIMENT_ID = "shareholder_pledge_data_feasibility_v1"
REPORT_PATH = Path("docs/research/shareholder-pledge-data-feasibility-v1.md")
ROW_LIMIT = 1_000
MIN_NONEMPTY_WINDOWS = 3
MIN_IDENTITY_COMPLETENESS = 0.95
PROBE_WINDOWS = (
    ("20150101", "20150131"),
    ("20190101", "20190131"),
    ("20230101", "20230131"),
    ("20260701", "20260724"),
)
REQUIRED_COLUMNS = {
    "ts_code",
    "ann_date",
    "holder_name",
    "pledge_amount",
    "start_date",
    "is_release",
    "release_date",
    "pledgor",
    "holding_amount",
    "pledged_amount",
    "p_total_ratio",
    "h_total_ratio",
}
IDENTITY_COLUMNS = (
    "ts_code",
    "holder_name",
    "start_date",
    "pledgor",
    "pledge_amount",
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="股东质押治理风险数据可行性 V1",
    category="data_feasibility",
    hypothesis="低质押治理风险能否由公告日可见的质押明细稳定重建",
    definition={
        "source": {"provider": "tushare", "endpoint": "pledge_detail"},
        "probe_windows": [list(item) for item in PROBE_WINDOWS],
        "required_columns": sorted(REQUIRED_COLUMNS),
        "identity_columns": list(IDENTITY_COLUMNS),
        "gates": {
            "all_windows_accessible": True,
            "minimum_nonempty_windows": MIN_NONEMPTY_WINDOWS,
            "row_count_must_be_below_api_limit": ROW_LIMIT,
            "identity_completeness_minimum": MIN_IDENTITY_COMPLETENESS,
            "same_identity_announcement_conflicts": 0,
            "future_release_mutations": 0,
        },
        "as_of_rule": (
            "signal_date仅可见ann_date不晚于signal_date的记录；"
            "若历史公告行携带晚于ann_date的解押状态则判定不可点时重建"
        ),
        "decision": "fail_before_backtest_if_any_gate_fails",
        "methodology_version": "v1",
    },
)


class PledgeDetailClient(Protocol):
    """声明股权质押明细接口，便于单测注入。"""

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        """按公告日期区间读取质押明细。"""


class TusharePledgeDetailClient:
    """真实 Tushare 质押明细客户端。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        """按官方公告日期参数读取固定窗口。"""
        return self._pro.pledge_detail(
            start_date=start_date,
            end_date=end_date,
        )


@dataclass(frozen=True)
class WindowProbe:
    """一次窗口探针的非敏感审计结果。"""

    start_date: str
    end_date: str
    status: str
    row_count: int
    symbol_count: int
    column_count: int
    error: str = ""


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client_factory: Callable[[], PledgeDetailClient] | None = None,
) -> dict[str, Any]:
    """先登记确定性指纹，再执行轻量数据探针。"""
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
    client_factory: Callable[[], PledgeDetailClient] | None,
) -> dict[str, Any]:
    """审计权限、覆盖、截断、事件身份和点时解押语义。"""
    client = _build_client(client_factory)
    frames: list[pd.DataFrame] = []
    probes: list[WindowProbe] = []
    observed_columns: set[str] = set()
    for start_date, end_date in PROBE_WINDOWS:
        try:
            frame = client.fetch(start_date, end_date)
            if not isinstance(frame, pd.DataFrame):
                raise TypeError("接口未返回DataFrame")
            frame = frame.copy()
            frame["_probe_start"] = start_date
            frame["_probe_end"] = end_date
            frames.append(frame)
            observed_columns.update(map(str, frame.columns))
            probes.append(
                WindowProbe(
                    start_date=start_date,
                    end_date=end_date,
                    status="OK" if not frame.empty else "EMPTY",
                    row_count=int(len(frame)),
                    symbol_count=_symbol_count(frame),
                    column_count=int(len(frame.columns) - 2),
                )
            )
        except Exception as error:
            probes.append(
                WindowProbe(
                    start_date=start_date,
                    end_date=end_date,
                    status="ERROR",
                    row_count=0,
                    symbol_count=0,
                    column_count=0,
                    error=_safe_error(error),
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
        "announcement_dates_complete": diagnostics["missing_announcement_dates"] == 0,
        "event_identity_reconstructible": (
            diagnostics["identity_completeness"] >= MIN_IDENTITY_COMPLETENESS
            and diagnostics["same_identity_announcement_conflicts"] == 0
        ),
        "release_state_point_in_time_safe": (
            diagnostics["future_release_mutations"] == 0
        ),
    }
    passed = all(checks.values())
    result = {
        "probe_windows": [asdict(item) for item in probes],
        "rows": int(len(combined)),
        "symbols": _symbol_count(combined),
        "observed_columns": sorted(observed_columns - {"_probe_start", "_probe_end"}),
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
    """用冻结规则检查质押事件能否按公告日稳定还原。"""
    if frame.empty or not REQUIRED_COLUMNS.issubset(frame.columns):
        return {
            "missing_announcement_dates": int(len(frame)),
            "identity_completeness": 0.0,
            "exact_duplicate_rows": 0,
            "same_identity_announcement_conflicts": 0,
            "future_release_mutations": 0,
            "released_rows": 0,
        }
    data = frame.copy()
    data["ann_date"] = pd.to_datetime(data["ann_date"], errors="coerce")
    data["release_date"] = pd.to_datetime(data["release_date"], errors="coerce")
    identity_complete = data[list(IDENTITY_COLUMNS)].notna().all(axis=1)
    lifecycle_columns = ["is_release", "release_date", "pledged_amount"]
    group_columns = [*IDENTITY_COLUMNS, "ann_date"]
    conflict_groups = (
        data.groupby(group_columns, dropna=False)[lifecycle_columns]
        .nunique(dropna=False)
        .gt(1)
        .any(axis=1)
    )
    released = data["is_release"].astype(str).str.strip().isin({"1", "是", "Y"})
    future_release = (
        released
        & data["release_date"].notna()
        & data["ann_date"].notna()
        & data["release_date"].gt(data["ann_date"])
    )
    return {
        "missing_announcement_dates": int(data["ann_date"].isna().sum()),
        "identity_completeness": float(identity_complete.mean()),
        "exact_duplicate_rows": int(
            data.drop(columns=["_probe_start", "_probe_end"], errors="ignore")
            .duplicated()
            .sum()
        ),
        "same_identity_announcement_conflicts": int(conflict_groups.sum()),
        "future_release_mutations": int(future_release.sum()),
        "released_rows": int(released.sum()),
    }


def render_report(result: dict[str, Any]) -> str:
    """生成人类可读的点时数据门禁报告。"""
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
    return f"""# 股东质押治理风险数据可行性 V1

本实验只验证数据口径，不读取收益，也不执行回测。

| 公告窗口 | 状态 | 行数 | 股票数 | 错误 |
|---|---|---:|---:|---|
{probes}

## 数据语义

- 总记录：{result['rows']}，覆盖股票：{result['symbols']}。
- 缺失必要字段：{', '.join(result['missing_columns']) or '无'}。
- 事件身份完整率：{diagnostics['identity_completeness']:.2%}。
- 完全重复记录：{diagnostics['exact_duplicate_rows']}。
- 同事件同公告日状态冲突：{diagnostics['same_identity_announcement_conflicts']}。
- 已解押记录：{diagnostics['released_rows']}。
- 公告行携带未来解押状态：{diagnostics['future_release_mutations']}。

## 可信门禁

{checks}

## 结论

- 决策：`{result['decision']}`。
- 原始业务记录未落盘。
- 若存在“未来解押状态”，仅按 `ann_date <= signal_date` 过滤仍会泄露后来信息；
  在缺少解押公告可见日期时，不得进入因子回测。
"""


def _build_client(
    client_factory: Callable[[], PledgeDetailClient] | None,
) -> PledgeDetailClient:
    """构造真实或测试客户端。"""
    if client_factory is not None:
        return client_factory()
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
    return TusharePledgeDetailClient(token)


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档可行性结论，失败候选同样进入实验历史。"""
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
            "全部点时数据门禁通过，可另行冻结因子设计"
            if result["passed"]
            else "质押明细无法通过冻结的点时数据门禁，未进入回测"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "质押数据可行性报告"),
            ExperimentArtifact("probe_windows", probes_path, "窗口探针元数据"),
        ],
    )


def _symbol_count(frame: pd.DataFrame) -> int:
    """安全统计股票数量。"""
    if frame.empty or "ts_code" not in frame:
        return 0
    return int(frame["ts_code"].nunique())


def _safe_error(error: Exception) -> str:
    """压缩接口异常，避免保存 Token 或请求细节。"""
    message = " ".join(str(error).split())
    return f"{type(error).__name__}: {message[:180]}"


def _data_version() -> str:
    """绑定客户端版本和固定探针口径。"""
    import tushare

    return f"tushare:{tushare.__version__}:pledge_detail_probe_v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
