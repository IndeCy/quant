"""边界资产配置候选与Quality相关性的滚动、残差和块自助审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "borderline_allocation_correlation_audit_v2"
REPORT_PATH = Path("docs/research/borderline-allocation-correlation-audit-v2.md")
QUALITY_ID = "quality_balanced_value_v1"
SOURCE_SERIES = {
    "nasdaq_gold_china_dividend_equal_v1": "纳指黄金红利低波等权",
    "china_tech_dividend_gold_equal_v1": "A股科技红利黄金等权",
}
START_DATE = "20200101"
ROLLING_WINDOW = 252
BOOTSTRAP_BLOCK = 20
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_SEED = 20260729
CORRELATION_LIMIT = 0.50

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="边界资产配置相关性稳健性审计 V2",
    category="strategy_attribution",
    hypothesis=(
        "两个固定资产配置候选的Quality相关性失败，是跨年份和市场Beta残差中都稳定存在，"
        "还是仅由有限样本与共同市场方向造成的边界噪声"
    ),
    definition={
        "source_experiments": list(SOURCE_SERIES),
        "quality_strategy": QUALITY_ID,
        "start_date": START_DATE,
        "statistics": {
            "pearson": True,
            "spearman": True,
            "rolling_window": ROLLING_WINDOW,
            "benchmark_residual": "510300_ols",
            "annual_regimes": True,
            "paired_block_bootstrap": {
                "block_days": BOOTSTRAP_BLOCK,
                "samples": BOOTSTRAP_SAMPLES,
                "seed": BOOTSTRAP_SEED,
            },
        },
        "classification": {
            "correlation_limit": CORRELATION_LIMIT,
            "robust_failure_probability_min": 0.75,
            "promotion_override": False,
        },
        "parameters_fixed_before_loading_series": True,
        "promotion_scope": "diagnostic_only_never_override_base_gate",
        "supersedes": "borderline_allocation_correlation_audit_v1_wrong_quality_target",
        "methodology_version": "paired_block_correlation_v2",
    },
)


def run_audit(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    normalized_as_of = str(as_of_date).replace("-", "")
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized_as_of,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, aligned = _calculate(paths, normalized_as_of)
        _complete_attempt(attempt, result, aligned)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    aligned = _load_aligned_returns(paths, as_of_date)
    if len(aligned) < 1200:
        raise ValueError(f"相关性共同样本不足: {len(aligned)}")
    candidate_results = {
        candidate_id: analyze_candidate(
            aligned[candidate_id],
            aligned[QUALITY_ID],
            aligned["benchmark"],
        )
        for candidate_id in SOURCE_SERIES
    }
    result = {
        "experiment_id": EXPERIMENT_ID,
        "as_of_date": as_of_date,
        "common_days": len(aligned),
        "start_date": aligned.index.min().strftime("%Y%m%d"),
        "end_date": aligned.index.max().strftime("%Y%m%d"),
        "candidates": candidate_results,
        "conclusion": {
            candidate_id: classify_correlation(metrics)
            for candidate_id, metrics in candidate_results.items()
        },
        "promotion_override": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, aligned


def analyze_candidate(
    candidate: pd.Series,
    quality: pd.Series,
    benchmark: pd.Series,
) -> dict[str, Any]:
    frame = pd.concat(
        [
            candidate.rename("candidate"),
            quality.rename("quality"),
            benchmark.rename("benchmark"),
        ],
        axis=1,
    ).dropna()
    rolling = frame["candidate"].rolling(ROLLING_WINDOW).corr(frame["quality"]).dropna()
    annual = {
        str(year): float(group["candidate"].corr(group["quality"]))
        for year, group in frame.groupby(frame.index.year)
        if len(group) >= 60
    }
    bootstrap = paired_block_bootstrap_correlations(
        frame["candidate"].to_numpy(),
        frame["quality"].to_numpy(),
        block_size=BOOTSTRAP_BLOCK,
        samples=BOOTSTRAP_SAMPLES,
        seed=BOOTSTRAP_SEED,
    )
    return {
        "pearson": float(frame["candidate"].corr(frame["quality"])),
        "spearman": float(frame["candidate"].corr(frame["quality"], method="spearman")),
        "benchmark_residual_correlation": residual_correlation(
            frame["candidate"],
            frame["quality"],
            frame["benchmark"],
        ),
        "rolling_252": {
            "median": float(rolling.median()),
            "p10": float(rolling.quantile(0.10)),
            "p90": float(rolling.quantile(0.90)),
            "max": float(rolling.max()),
            "share_above_limit": float(rolling.gt(CORRELATION_LIMIT).mean()),
        },
        "annual": annual,
        "bootstrap": {
            "p05": float(np.quantile(bootstrap, 0.05)),
            "median": float(np.quantile(bootstrap, 0.50)),
            "p95": float(np.quantile(bootstrap, 0.95)),
            "probability_above_limit": float(np.mean(bootstrap > CORRELATION_LIMIT)),
        },
    }


def paired_block_bootstrap_correlations(
    left: np.ndarray,
    right: np.ndarray,
    *,
    block_size: int,
    samples: int,
    seed: int,
) -> np.ndarray:
    if len(left) != len(right) or len(left) < block_size:
        raise ValueError("块自助样本长度非法")
    rng = np.random.default_rng(seed)
    length = len(left)
    block_count = int(np.ceil(length / block_size))
    max_start = length - block_size
    correlations = np.empty(samples, dtype=float)
    for sample in range(samples):
        starts = rng.integers(0, max_start + 1, size=block_count)
        indices = np.concatenate(
            [np.arange(start, start + block_size) for start in starts]
        )[:length]
        correlations[sample] = np.corrcoef(left[indices], right[indices])[0, 1]
    return correlations


def residual_correlation(
    candidate: pd.Series,
    quality: pd.Series,
    benchmark: pd.Series,
) -> float:
    design = np.column_stack([np.ones(len(benchmark)), benchmark.to_numpy()])
    candidate_beta = np.linalg.lstsq(design, candidate.to_numpy(), rcond=None)[0]
    quality_beta = np.linalg.lstsq(design, quality.to_numpy(), rcond=None)[0]
    candidate_residual = candidate.to_numpy() - design @ candidate_beta
    quality_residual = quality.to_numpy() - design @ quality_beta
    return float(np.corrcoef(candidate_residual, quality_residual)[0, 1])


def classify_correlation(metrics: dict[str, Any]) -> str:
    probability = float(metrics["bootstrap"]["probability_above_limit"])
    if float(metrics["pearson"]) <= CORRELATION_LIMIT:
        return "WITHIN_LIMIT"
    if probability >= 0.75:
        return "ROBUST_DIVERSIFICATION_FAILURE"
    return "BORDERLINE_UNCERTAIN_NO_OVERRIDE"


def _load_aligned_returns(paths: RuntimePaths, as_of_date: str) -> pd.DataFrame:
    series = {
        candidate_id: _load_experiment_nav(paths.system_state_path, candidate_id)
        for candidate_id in SOURCE_SERIES
    }
    with sqlite3.connect(
        f"file:{paths.monitoring_path}?mode=ro",
        uri=True,
    ) as connection:
        quality = pd.read_sql_query(
            """
            SELECT trade_date, nav
            FROM strategy_nav_daily
            WHERE strategy_id = ? AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            connection,
            params=[QUALITY_ID, START_DATE, as_of_date],
        )
        benchmark = pd.read_sql_query(
            """
            SELECT trade_date, benchmark_nav
            FROM market_state_daily
            WHERE benchmark_id = '510300' AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            connection,
            params=[START_DATE, as_of_date],
        )
    navs = {
        candidate_id: _nav_series(frame)
        for candidate_id, frame in series.items()
    }
    navs[QUALITY_ID] = _nav_series(quality)
    navs["benchmark"] = _nav_series(
        benchmark.rename(columns={"benchmark_nav": "nav"})
    )
    returns = pd.concat(
        {name: nav.pct_change() for name, nav in navs.items()},
        axis=1,
        sort=True,
    )
    return returns.dropna()


def _load_experiment_nav(path: Path, experiment_id: str) -> pd.DataFrame:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        run = connection.execute(
            """
            SELECT run_id
            FROM experiment_runs
            WHERE experiment_id = ? AND status = 'SUCCESS'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [experiment_id],
        ).fetchone()
        if run is None:
            raise ValueError(f"缺少实验序列: {experiment_id}")
        return pd.read_sql_query(
            """
            SELECT trade_date, nav
            FROM experiment_series_daily
            WHERE experiment_id = ? AND run_id = ? AND series_id = ?
              AND trade_date >= ?
            ORDER BY trade_date
            """,
            connection,
            params=[experiment_id, str(run[0]), experiment_id, START_DATE],
        )


def _nav_series(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series(
        pd.to_numeric(frame["nav"], errors="coerce").to_numpy(),
        index=pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d"),
        dtype=float,
    ).dropna()
    return result[~result.index.duplicated(keep="last")].sort_index()


def render_report(result: dict[str, Any]) -> str:
    sections = []
    for candidate_id, metrics in result["candidates"].items():
        annual = "；".join(
            f"{year}={value:.3f}"
            for year, value in metrics["annual"].items()
        )
        sections.append(
            f"""## {SOURCE_SERIES[candidate_id]}

- 全期 Pearson / Spearman：{metrics['pearson']:.3f} / {metrics['spearman']:.3f}
- 剔除510300线性Beta后的残差相关：{metrics['benchmark_residual_correlation']:.3f}
- 252日滚动中位 / P10 / P90：{metrics['rolling_252']['median']:.3f} / {metrics['rolling_252']['p10']:.3f} / {metrics['rolling_252']['p90']:.3f}
- 滚动窗口高于0.50比例：{metrics['rolling_252']['share_above_limit']:.1%}
- 20日块自助90%区间：[{metrics['bootstrap']['p05']:.3f}, {metrics['bootstrap']['p95']:.3f}]
- 自助样本相关性高于0.50概率：{metrics['bootstrap']['probability_above_limit']:.1%}
- 年度相关：{annual}
- 分类：{result['conclusion'][candidate_id]}
"""
        )
    return f"""# 边界资产配置相关性稳健性审计 V2

- 共同样本：{result['common_days']}日，{result['start_date']} 至 {result['end_date']}。
- V2修正：相关性目标与原策略门槛一致，固定为quality_balanced_value_v1；V1误用quality_overlay，不作为结论。
- 预注册阈值：Quality日收益相关性绝对值不高于0.50。
- 统计：Pearson、Spearman、252日滚动、510300残差、20日配对块自助5000次。
- 本审计只解释边界失败，不允许推翻原实验门槛或自动晋级。

{''.join(sections)}
"""


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    aligned: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    correlations = attempt.output_dir / "correlation_audit.json"
    correlations.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    returns_path = attempt.output_dir / "aligned_daily_returns.csv"
    aligned.rename_axis("trade_date").reset_index().to_csv(
        returns_path,
        index=False,
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=(
            "边界相关性稳健性审计完成；原实验门槛保持不变，禁止用审计结果事后晋级"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "相关性稳健性报告"),
            ExperimentArtifact("diagnostics", correlations, "完整相关性统计"),
            ExperimentArtifact("aligned_returns", returns_path, "共同日收益样本"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    source_parts: list[str] = []
    try:
        with sqlite3.connect(
            f"file:{paths.system_state_path}?mode=ro",
            uri=True,
        ) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for experiment_id in SOURCE_SERIES:
                summary = None
                if {"experiment_runs", "experiment_series_daily"} <= tables:
                    summary = connection.execute(
                        """
                        SELECT r.run_id, COUNT(s.trade_date), MAX(s.trade_date)
                        FROM experiment_runs r
                        LEFT JOIN experiment_series_daily s
                          ON s.run_id = r.run_id
                         AND s.experiment_id = r.experiment_id
                         AND s.series_id = r.experiment_id
                        WHERE r.experiment_id = ? AND r.status = 'SUCCESS'
                          AND r.run_id = (
                              SELECT run_id
                              FROM experiment_runs
                              WHERE experiment_id = ? AND status = 'SUCCESS'
                              ORDER BY created_at DESC
                              LIMIT 1
                          )
                        GROUP BY r.run_id
                        """,
                        [experiment_id, experiment_id],
                    ).fetchone()
                source_parts.append(
                    f"{experiment_id}:{'none' if summary is None else ':'.join(map(str, summary))}"
                )
    except sqlite3.DatabaseError:
        source_parts.extend(
            f"{experiment_id}:none"
            for experiment_id in SOURCE_SERIES
        )
    monitoring = paths.monitoring_path.stat()
    source_parts.append(
        f"monitoring:{monitoring.st_size}:{monitoring.st_mtime_ns}"
    )
    return "|".join(source_parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260728")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_audit(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
