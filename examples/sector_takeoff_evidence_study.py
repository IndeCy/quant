"""板块起飞前证据链：历史事件验证与当前候选扫描。

研究用途：
- 用东方财富概念板块日线回放 2020 年以来的月末信号；
- 冻结“未来 60 日上涨 30% 且跑赢沪深 300 20%”为严格起飞事件；
- 仅用信号日及以前的价格、成交额、换手构造早期证据分；
- 当前成分只用于最新候选的股票映射，不用于历史标签。

本脚本不会修改策略、调度、生产数据库，也不会发送通知。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable

import duckdb
import pandas as pd
import tushare as ts

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.sector_takeoff_evidence_support import (
    build_monthly_sector_samples,
    case_study_timeline,
    current_candidate_snapshot,
    evaluate_frozen_score,
    merge_recent_breadth,
)
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


EXPERIMENT_ID = "sector_takeoff_evidence_v1"
REPORT_PATH = Path("docs/research/sector-takeoff-evidence-v1.md")
HISTORY_START = "20200101"
EVALUATION_START = "20210101"
EVALUATION_END = "20251231"
BREADTH_START = "20241220"
AS_OF_DATE = "20260728"
REQUEST_INTERVAL_SECONDS = 0.35
CASE_CODES = ["BK1128.DC", "BK0963.DC"]

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="板块起飞前证据链历史验证 V1",
    category="sector_event_study",
    hypothesis=(
        "概念板块在大幅起飞前，是否存在可复现的相对强度、收益加速度、"
        "成交额扩张、换手扩张和接近阶段新高的联合路径"
    ),
    definition={
        "source": {
            "provider": "tushare",
            "daily_endpoint": "dc_daily",
            "breadth_endpoint": "dc_index",
            "history_start": HISTORY_START,
            "as_of_date": AS_OF_DATE,
            "universe": "all rows whose point-in-time dc_daily category is 概念板块",
            "benchmark": "000300.SH index_daily local cache",
        },
        "sampling": {
            "frequency": "each board's last trading observation per month",
            "evaluation_start": EVALUATION_START,
            "evaluation_end": EVALUATION_END,
        },
        "strict_takeoff_label": {
            "forward_trading_days": 60,
            "board_return_min": 0.30,
            "excess_vs_csi300_min": 0.20,
            "label_is_never_used_in_current_ranking": True,
        },
        "point_in_time_features": {
            "relative_return_60d_weight": 0.25,
            "return_acceleration_weight": 0.20,
            "amount_expansion_20d_vs_120d_weight": 0.20,
            "turnover_expansion_20d_vs_120d_weight": 0.15,
            "distance_to_120d_high_weight": 0.20,
            "maturity_penalty": {
                "ret_60d_above_50pct": 10,
                "ret_120d_above_100pct": 15,
                "turnover_ratio_above_3x": 10,
            },
        },
        "auxiliary_recent_only": {
            "breadth_start": BREADTH_START,
            "fields": ["up_num", "down_num", "leading_pct"],
            "excluded_from_main_score": True,
        },
        "frozen_validation_gates": {
            "top_decile_hit_lift_min": 1.5,
            "top_decile_mean_excess_positive": True,
            "top_minus_bottom_hit_gap_min": 0.05,
            "positive_years_min": 4,
            "score_future_excess_spearman_min": 0.08,
        },
        "known_calibration_cases": {
            "BK1128.DC": "CPO概念",
            "BK0963.DC": "商业航天",
        },
        "survivorship_control": (
            "历史面板按当日dc_daily的category纳入；当前名称和成分只用于最新映射，"
            "不反向决定历史样本"
        ),
        "execution": "research_only_no_orders_no_scheduler_no_bark",
        "methodology_version": "v1_frozen_before_full_panel_download",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str = AS_OF_DATE,
    *,
    force: bool = False,
    client: Any | None = None,
    request_interval_seconds: float = REQUEST_INTERVAL_SECONDS,
    source_dataset: Path | None = None,
) -> dict[str, Any]:
    """登记研究身份后下载完整板块面板并完成冻结验证。"""
    if as_of_date != AS_OF_DATE:
        raise ValueError(
            f"V1 已冻结数据截止日为 {AS_OF_DATE}；其他截止日需建立新版本"
        )
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=f"tushare_dc_daily:{HISTORY_START}:{as_of_date}",
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(
            paths,
            attempt,
            as_of_date,
            client=client,
            request_interval_seconds=request_interval_seconds,
            source_dataset=source_dataset,
        )
        _complete(attempt, result)
        return _public_result(result)
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    attempt: ResearchAttempt,
    as_of_date: str,
    *,
    client: Any | None,
    request_interval_seconds: float,
    source_dataset: Path | None,
) -> dict[str, Any]:
    pro = client or _build_client()
    benchmark = _load_benchmark(paths, HISTORY_START, as_of_date)
    latest_index = _request_with_retry(
        lambda: pro.dc_index(trade_date=as_of_date),
        f"dc_index:{as_of_date}",
    )
    if latest_index.empty:
        raise RuntimeError(f"{as_of_date} DC板块列表为空")
    if source_dataset is not None:
        daily, breadth = _load_research_dataset(source_dataset)
        _validate_reused_dataset(daily, breadth, as_of_date)
    else:
        trading_dates = _load_trading_dates(paths, HISTORY_START, as_of_date)
        daily = _fetch_by_trade_date(
            trading_dates,
            lambda trade_date: pro.dc_daily(trade_date=trade_date),
            label="dc_daily",
            interval_seconds=request_interval_seconds,
        )
        breadth_dates = [
            value for value in trading_dates if value >= BREADTH_START
        ]
        breadth = _fetch_by_trade_date(
            breadth_dates,
            lambda trade_date: pro.dc_index(trade_date=trade_date),
            label="dc_index",
            interval_seconds=request_interval_seconds,
            allow_empty_before=BREADTH_START,
        )
    if daily.empty:
        raise RuntimeError("DC板块历史面板为空")

    samples = build_monthly_sector_samples(daily, benchmark)
    samples = merge_recent_breadth(samples, breadth)
    evaluation = evaluate_frozen_score(samples)
    candidates = current_candidate_snapshot(samples, latest_index, top_n=30)
    cases = case_study_timeline(samples, latest_index, CASE_CODES)

    dataset_path = attempt.output_dir / "sector_takeoff_evidence.duckdb"
    candidates_path = attempt.output_dir / "current_candidates.csv"
    cases_path = attempt.output_dir / "known_case_timeline.csv"
    deciles_path = attempt.output_dir / "score_deciles.csv"
    folds_path = attempt.output_dir / "annual_validation.csv"
    _write_research_dataset(dataset_path, daily, breadth, samples)
    candidates.to_csv(candidates_path, index=False)
    cases.to_csv(cases_path, index=False)
    evaluation["deciles"].to_csv(deciles_path, index=False)
    evaluation["folds"].to_csv(folds_path, index=False)

    metrics = {
        key: value
        for key, value in evaluation.items()
        if key not in {"deciles", "folds"}
    }
    metrics.update(
        {
            "as_of_date": as_of_date,
            "daily_rows": int(len(daily)),
            "daily_board_count": int(daily["ts_code"].nunique()),
            "daily_first_date": str(daily["trade_date"].min()),
            "daily_last_date": str(daily["trade_date"].max()),
            "breadth_rows": int(len(breadth)),
            "breadth_first_date": (
                str(breadth["trade_date"].min()) if not breadth.empty else ""
            ),
            "breadth_last_date": (
                str(breadth["trade_date"].max()) if not breadth.empty else ""
            ),
            "monthly_sample_rows": int(len(samples)),
            "current_candidate_count": int(len(candidates)),
            "known_case_event_count": int(len(cases)),
            "current_top_candidates": _records(candidates.head(15)),
            "known_case_events": _records(cases),
        }
    )
    report = render_report(metrics, evaluation["deciles"], evaluation["folds"])
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report, encoding="utf-8")
    return {
        "metrics": metrics,
        "artifacts": [
            ExperimentArtifact("summary", summary_path, "板块起飞前证据研究摘要"),
            ExperimentArtifact("report", report_path, "板块起飞前证据研究报告"),
            ExperimentArtifact(
                "research_dataset",
                dataset_path,
                "DC板块日线、宽度与月末样本研究库",
            ),
            ExperimentArtifact(
                "current_candidates",
                candidates_path,
                "当前候选板块排名",
            ),
            ExperimentArtifact(
                "known_cases",
                cases_path,
                "CPO与商业航天校准事件",
            ),
            ExperimentArtifact("deciles", deciles_path, "证据分十分位验证"),
            ExperimentArtifact("annual_validation", folds_path, "年度折叠验证"),
        ],
    }


def _complete(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    metrics = result["metrics"]
    passed = bool(metrics["passed"])
    complete_research_attempt(
        attempt,
        metrics=metrics,
        outcome="PASSED_VALIDATION" if passed else "REJECTED",
        decision_reason=(
            "冻结证据分通过全部历史与年度稳定性门禁，可用于研究雷达排序"
            if passed
            else "冻结证据分未通过全部稳定性门禁；保留事件证据与当前候选，禁止升级为交易策略"
        ),
        artifacts=result["artifacts"],
    )


def render_report(
    metrics: dict[str, Any],
    deciles: pd.DataFrame,
    folds: pd.DataFrame,
) -> str:
    """生成可审计的中文研究报告。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：`{name}`"
        for name, passed in metrics["checks"].items()
    )
    decile_rows = "\n".join(
        "| {score_decile:.0f} | {samples:.0f} | {strict_hit_rate:.2%} | "
        "{mean_future_return:.2%} | {mean_future_excess:.2%} |".format(**row)
        for row in deciles.to_dict("records")
    )
    fold_rows = "\n".join(
        "| {year} | {samples:.0f} | {baseline_hit_rate:.2%} | "
        "{top_decile_hit_rate:.2%} | {top_decile_mean_excess:.2%} |".format(
            **row
        )
        for row in folds.to_dict("records")
    )
    candidate_rows = "\n".join(
        f"| {index + 1} | {row.get('name') or '-'} | {row['ts_code']} | "
        f"{row['evidence_score']:.1f} | {row['ret_60']:.2%} | "
        f"{row['amount_ratio_20_120']:.2f} | {row['turnover_ratio_20_120']:.2f} | "
        f"{_percent(row.get('breadth_20'))} |"
        for index, row in enumerate(metrics["current_top_candidates"])
    )
    case_rows = "\n".join(
        f"| {row.get('name') or '-'} | {row['signal_date']} | "
        f"{_number(row.get('evidence_score'), 1)} | "
        f"{_percentage(row.get('ret_60'))} | "
        f"{_number(row.get('amount_ratio_20_120'), 2)} | "
        f"{_percentage(row.get('future_ret_60'))} | "
        f"{_percentage(row.get('future_excess_60'))} |"
        for row in metrics["known_case_events"]
    ) or "| - | - | - | - | - | - | - |"
    verdict = (
        "通过：该证据链可进入研究雷达，但仍不是买卖策略。"
        if metrics["passed"]
        else "未通过：证据可用于案例解释和候选排查，但不足以作为独立交易规则。"
    )
    return f"""# 板块起飞前证据链历史验证 V1

数据截止 `{metrics['as_of_date']}`。本研究只做板块事件验证和研究优先级，
不接入策略、scheduler、订单或 Bark。

## 冻结定义

- 样本：每个东方财富概念板块的月末最后交易日。
- 严格“起飞”：未来 60 个交易日上涨至少 30%，且跑赢沪深 300 至少 20%。
- 证据只使用信号日及以前：60 日相对强度、20/60 日收益加速度、
  20/120 日成交额扩张、20/120 日换手扩张、距离 120 日高点。
- 60 日涨幅超过 50%、120 日涨幅超过 100% 或换手扩张超过 3 倍会扣成熟度分。
- 上涨/下跌家数历史仅从 2024-12-20 开始，所以只作近期辅助，未进入主分数。

## 数据完整性

- 日线：{metrics['daily_rows']:,} 行，{metrics['daily_board_count']} 个板块，
  `{metrics['daily_first_date']}` 至 `{metrics['daily_last_date']}`。
- 宽度辅助：{metrics['breadth_rows']:,} 行，
  `{metrics['breadth_first_date']}` 至 `{metrics['breadth_last_date']}`。
- 可评估月末样本：{metrics['sample_count']:,}，
  严格起飞事件：{metrics['strict_takeoff_count']:,}。

## 冻结验证

- 全样本起飞率：{metrics['baseline_hit_rate']:.2%}。
- 证据分最高十分位起飞率：{metrics['top_decile_hit_rate']:.2%}，
  提升倍数 {metrics['top_hit_lift']:.2f}。
- 最高十分位未来 60 日平均超额：{metrics['top_decile_mean_excess']:.2%}。
- 分数与未来超额 Spearman：{metrics['score_future_excess_spearman']:.3f}。
- 年度正超额：{metrics['positive_fold_count']}/{metrics['fold_count']}。

{checks}

结论：**{verdict}**

## 十分位结果

| 分位 | 样本 | 起飞率 | 未来60日收益 | 未来60日超额 |
|---:|---:|---:|---:|---:|
{decile_rows}

## 年度折叠

| 年份 | 样本 | 基准起飞率 | 最高十分位起飞率 | 最高十分位平均超额 |
|---|---:|---:|---:|---:|
{fold_rows}

## 已知案例：CPO 与商业航天

| 板块 | 信号月末 | 证据分 | 当时60日涨幅 | 成交额扩张 | 后续60日收益 | 后续超额 |
|---|---|---:|---:|---:|---:|---:|
{case_rows}

这里的信号日由统一事件定义产生，不是手工选择新闻日前夕。CPO 板块指数本身
从 2023-02-10 才有数据，因此最初一段行情无法满足 120 日预热窗口；这是明确缺口。

## 当前研究候选（尚不是买入清单）

| 排名 | 板块 | 代码 | 证据分 | 60日涨幅 | 成交额扩张 | 换手扩张 | 20日宽度 |
|---:|---|---|---:|---:|---:|---:|---:|
{candidate_rows}

## 使用边界

- 当前板块名称仅用于展示，历史样本按当日 `dc_daily.category=概念板块` 纳入。
- 当前成分不能反向当作历史成分；个股映射必须单独标注“当前成员”。
- 证据分衡量“值得继续研究”，不证明产业基本面，也不等同于交易胜率。
- 正式候选还需补齐政策/订单/产能/利润预告的公告时点证据，并做股票层面可交易性检查。
"""


def _load_trading_dates(
    paths: RuntimePaths,
    start_date: str,
    end_date: str,
) -> list[str]:
    with duckdb.connect(str(paths.benchmark_increment_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT trade_date
            FROM index_daily
            WHERE ts_code = '000300.SH'
              AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            [start_date, end_date],
        ).fetchall()
    values = [str(row[0]) for row in rows]
    if not values or values[-1] != end_date:
        raise RuntimeError(
            f"沪深300交易日历未覆盖截止日 {end_date}，最新={values[-1] if values else '-'}"
        )
    return values


def _write_research_dataset(
    path: Path,
    daily: pd.DataFrame,
    breadth: pd.DataFrame,
    samples: pd.DataFrame,
) -> None:
    """用项目既有 DuckDB 原生落盘，避免引入额外 Parquet 引擎。"""
    with duckdb.connect(str(path)) as con:
        con.register("daily_input", daily)
        con.register("breadth_input", breadth)
        con.register("samples_input", samples)
        con.execute("CREATE TABLE dc_concept_daily AS SELECT * FROM daily_input")
        con.execute(
            "CREATE TABLE dc_concept_breadth AS SELECT * FROM breadth_input"
        )
        con.execute(
            "CREATE TABLE monthly_sector_samples AS SELECT * FROM samples_input"
        )
        con.execute(
            "CREATE INDEX daily_code_date ON dc_concept_daily(ts_code, trade_date)"
        )
        con.execute(
            "CREATE INDEX samples_code_date "
            "ON monthly_sector_samples(ts_code, trade_date)"
        )


def _load_research_dataset(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """复用同一冻结定义下已完整落盘、但登记阶段失败的研究源数据。"""
    if not path.exists():
        raise FileNotFoundError(path)
    with duckdb.connect(str(path), read_only=True) as con:
        tables = {
            str(row[0])
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main'"
            ).fetchall()
        }
        required = {"dc_concept_daily", "dc_concept_breadth"}
        if not required.issubset(tables):
            raise ValueError(
                f"复用研究库缺少表: {sorted(required - tables)}"
            )
        daily = con.execute("SELECT * FROM dc_concept_daily").fetchdf()
        breadth = con.execute("SELECT * FROM dc_concept_breadth").fetchdf()
    return daily, breadth


def _validate_reused_dataset(
    daily: pd.DataFrame,
    breadth: pd.DataFrame,
    as_of_date: str,
) -> None:
    """复用前验证行数和日期边界，避免拿不完整失败产物继续计算。"""
    daily_dates = daily["trade_date"].astype(str)
    breadth_dates = breadth["trade_date"].astype(str)
    checks = {
        "daily_rows": len(daily) == 1_419_279,
        "daily_start": str(daily_dates.min()) == "20200102",
        "daily_end": str(daily_dates.max()) == as_of_date,
        "breadth_rows": len(breadth) == 252_168,
        "breadth_start": str(breadth_dates.min()) == BREADTH_START,
        "breadth_end": str(breadth_dates.max()) == as_of_date,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"复用研究库完整性校验失败: {failed}")


def _load_benchmark(
    paths: RuntimePaths,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    with duckdb.connect(str(paths.benchmark_increment_path), read_only=True) as con:
        return con.execute(
            """
            SELECT trade_date, close
            FROM index_daily
            WHERE ts_code = '000300.SH'
              AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            [start_date, end_date],
        ).fetchdf()


def _build_client() -> Any:
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN")
    return ts.pro_api(token)


def _fetch_by_trade_date(
    trading_dates: list[str],
    fetcher: Callable[[str], pd.DataFrame],
    *,
    label: str,
    interval_seconds: float,
    allow_empty_before: str | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    empty_dates: list[str] = []
    total = len(trading_dates)
    for index, trade_date in enumerate(trading_dates, start=1):
        frame = _request_with_retry(
            lambda value=trade_date: fetcher(value),
            f"{label}:{trade_date}",
        )
        if frame.empty and (
            allow_empty_before is None or trade_date >= allow_empty_before
        ):
            empty_dates.append(trade_date)
        elif not frame.empty:
            frames.append(frame)
        if index == 1 or index == total or index % 50 == 0:
            print(
                f"{label} progress {index}/{total} ({trade_date}), "
                f"rows={sum(len(item) for item in frames)}",
                flush=True,
            )
        if interval_seconds > 0:
            time.sleep(interval_seconds)
    if empty_dates:
        raise RuntimeError(
            f"{label} 存在 {len(empty_dates)} 个空交易日，示例={empty_dates[:10]}"
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _request_with_retry(
    operation: Callable[[], pd.DataFrame],
    label: str,
    *,
    retries: int = 4,
) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            frame = operation()
            if not isinstance(frame, pd.DataFrame):
                raise TypeError(f"{label} 未返回 DataFrame")
            return frame
        except Exception as error:
            last_error = error
            if attempt == retries:
                break
            time.sleep(float(attempt))
    assert last_error is not None
    raise RuntimeError(f"{label} 请求失败: {type(last_error).__name__}: {last_error}")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _percent(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.1%}"


def _number(value: Any, digits: int) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}"


def _percentage(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    return {**result["metrics"], "reused": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=AS_OF_DATE)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--request-interval-seconds",
        type=float,
        default=REQUEST_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--source-dataset",
        type=Path,
        help="复用同一冻结定义下已完整落盘的研究 DuckDB",
    )
    args = parser.parse_args()
    result = run_study(
        get_runtime_paths(),
        args.as_of_date,
        force=args.force,
        request_interval_seconds=args.request_interval_seconds,
        source_dataset=args.source_dataset,
    )
    print(
        {
            "passed": result.get("passed"),
            "sample_count": result.get("sample_count"),
            "strict_takeoff_count": result.get("strict_takeoff_count"),
            "top_hit_lift": result.get("top_hit_lift"),
            "top_decile_mean_excess": result.get("top_decile_mean_excess"),
            "current_top_candidates": result.get("current_top_candidates", [])[:10],
            "reused": result.get("reused"),
        }
    )


if __name__ == "__main__":
    main()
