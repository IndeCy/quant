"""机构调研关注度因子的点时数据可行性审计。"""

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


EXPERIMENT_ID = "institutional_survey_data_feasibility_v1"
REPORT_PATH = Path("docs/research/institutional-survey-data-feasibility-v1.md")
ROW_LIMIT = 100
PROBE_WINDOWS = (
    ("20150101", "20150107"),
    ("20190101", "20190107"),
    ("20230101", "20230107"),
    ("20260701", "20260707"),
)
REQUIRED_COLUMNS = {
    "ts_code",
    "name",
    "surv_date",
    "fund_visitors",
    "rece_mode",
    "rece_org",
    "org_type",
}
VISIBILITY_COLUMNS = {"ann_date", "pub_date", "publish_date", "disclosure_date"}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="机构调研关注度数据可行性 V1",
    category="data_feasibility",
    hypothesis="机构调研记录能否用公开时间戳构造点时机构关注因子",
    definition={
        "source": {"provider": "tushare", "endpoint": "stk_surv"},
        "probe_windows": [list(item) for item in PROBE_WINDOWS],
        "required_columns": sorted(REQUIRED_COLUMNS),
        "required_visibility_columns_any": sorted(VISIBILITY_COLUMNS),
        "gates": {
            "all_windows_accessible": True,
            "minimum_nonempty_windows": 3,
            "row_count_must_be_below_api_limit": ROW_LIMIT,
            "public_visibility_timestamp_required": True,
            "survey_date_complete": True,
        },
        "forbidden_assumption": "surv_date_plus_fixed_lag_as_publication_date",
        "decision": "fail_before_cache_or_backtest_if_any_gate_fails",
        "methodology_version": "v1",
    },
)


class SurveyClient(Protocol):
    """声明机构调研接口。"""

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        """按调研日期区间读取记录。"""


class TushareSurveyClient:
    """真实 Tushare 机构调研客户端。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        """调用官方 stk_surv 接口。"""
        return self._pro.stk_surv(
            start_date=start_date,
            end_date=end_date,
        )


@dataclass(frozen=True)
class WindowProbe:
    """一次窗口探针的非敏感结果。"""

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
    client_factory: Callable[[], SurveyClient] | None = None,
) -> dict[str, Any]:
    """先登记指纹，再执行少量真实接口探针。"""
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
        _complete(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    client_factory: Callable[[], SurveyClient] | None,
) -> dict[str, Any]:
    """检查权限、覆盖、截断和公开可见时点。"""
    client = _build_client(client_factory)
    probes: list[WindowProbe] = []
    frames: list[pd.DataFrame] = []
    observed_columns: set[str] = set()
    for start_date, end_date in PROBE_WINDOWS:
        try:
            frame = client.fetch(start_date, end_date)
            if not isinstance(frame, pd.DataFrame):
                raise TypeError("接口未返回DataFrame")
            frames.append(frame.copy())
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
    survey_dates = (
        pd.to_datetime(combined["surv_date"], errors="coerce")
        if "surv_date" in combined
        else pd.Series(dtype="datetime64[ns]")
    )
    checks = {
        "all_windows_accessible": all(item.status != "ERROR" for item in probes),
        "cross_period_coverage": sum(
            item.status == "OK" for item in probes
        ) >= 3,
        "required_columns_present": REQUIRED_COLUMNS.issubset(observed_columns),
        "no_window_hits_row_limit": all(
            item.row_count < ROW_LIMIT for item in probes
        ),
        "public_visibility_timestamp_present": bool(
            VISIBILITY_COLUMNS & observed_columns
        ),
        "survey_dates_complete": (
            len(combined) > 0 and int(survey_dates.isna().sum()) == 0
        ),
    }
    passed = all(checks.values())
    result = {
        "probe_windows": [asdict(item) for item in probes],
        "rows": int(len(combined)),
        "symbols": _symbol_count(combined),
        "observed_columns": sorted(observed_columns),
        "missing_columns": sorted(REQUIRED_COLUMNS - observed_columns),
        "visibility_columns_found": sorted(
            VISIBILITY_COLUMNS & observed_columns
        ),
        "checks": checks,
        "passed": passed,
        "decision": (
            "ELIGIBLE_FOR_CACHE_DESIGN"
            if passed
            else "REJECTED_BEFORE_CACHE_OR_BACKTEST"
        ),
        "raw_rows_persisted": False,
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def render_report(result: dict[str, Any]) -> str:
    """生成机构调研数据门禁报告。"""
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
    return f"""# 机构调研关注度数据可行性 V1

| 调研窗口 | 状态 | 行数 | 股票数 | 错误 |
|---|---|---:|---:|---|
{probes}

- 总记录：{result['rows']}，覆盖股票：{result['symbols']}。
- 缺失必要业务字段：{', '.join(result['missing_columns']) or '无'}。
- 公开可见时间字段：
  {', '.join(result['visibility_columns_found']) or '无'}。

## 可信门禁

{checks}

## 结论

- 决策：`{result['decision']}`。
- `surv_date` 只表示调研发生日，不等于记录公开日。
- 不允许用固定延迟伪造公告日期；原始记录未缓存，也未执行回测。
"""


def _build_client(
    client_factory: Callable[[], SurveyClient] | None,
) -> SurveyClient:
    """构造真实或测试客户端。"""
    if client_factory is not None:
        return client_factory()
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
    return TushareSurveyClient(token)


def _complete(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档门禁结论，失败候选同样防重复。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    probes_path = attempt.output_dir / "probe_windows.csv"
    pd.DataFrame(result["probe_windows"]).to_csv(probes_path, index=False)
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if result["passed"] else "REJECTED",
        decision_reason=(
            "机构调研数据具有公开时间戳，可另行设计缓存"
            if result["passed"]
            else "机构调研缺少公开时间戳或命中接口截断，不进入缓存和回测"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "机构调研数据门禁报告"),
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
    """绑定 SDK 和固定探针口径。"""
    import tushare

    return f"tushare:{tushare.__version__}:stk_surv_probe_v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
