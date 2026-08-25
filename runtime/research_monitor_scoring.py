"""投研机会监控的评分和证据规则。"""

from __future__ import annotations

from typing import Any


def classify_watch_level(
    metrics: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    theme: dict[str, Any] | None = None,
) -> str:
    if metrics.get("data_status") != "ok":
        return "B"
    evidence = evidence or build_powerlaw_evidence(None, metrics, theme)
    if is_case_study_theme(theme):
        return "案例" if evidence["maturity_score"] >= 60 else "校准"
    if evidence["disconfirm_triggered"]:
        return "淘汰"
    if evidence["opportunity_phase"] == "LateConfirmed":
        return "成熟"
    score = float(evidence["early_signal_score"])
    if score >= 75:
        return "S"
    if score >= 55:
        return "A"
    return "B"


def build_powerlaw_evidence(
    _paths: object | None,
    metrics: dict[str, Any],
    theme: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把价格、相对强弱和财务验证压缩成研究雷达证据，不作为交易信号。"""
    if metrics.get("data_status") != "ok":
        return {
            "trend_confirmed": False,
            "relative_strength_confirmed": False,
            "finance_growth_confirmed": False,
            "cash_quality_confirmed": False,
            "high_resilience_confirmed": False,
            "disconfirm_triggered": False,
            "powerlaw_score": 0.0,
            "early_signal_score": 0.0,
            "maturity_score": 0.0,
            "crowding_score": 0.0,
            "opportunity_phase": "Observation",
            "upgrade_path": "Observation",
        }
    ret_1y = metric_float(metrics, "ret_1y", metric_float(metrics, "ret_250d"))
    ret_2y = metric_float(metrics, "ret_2y")
    relative_strength = metric_float(metrics, "relative_strength_250d")
    distance_to_high = metric_float(metrics, "distance_to_high_250d", -1.0)
    revenue_yoy = metric_float(metrics, "tr_yoy")
    profit_yoy = metric_float(metrics, "netprofit_yoy")
    gross_margin = metric_float(metrics, "grossprofit_margin")
    ocf_to_or = metric_float(metrics, "ocf_to_or")
    trend_confirmed = ret_1y > 0.3 or ret_2y > 0.6
    relative_strength_confirmed = relative_strength > 0.2
    high_resilience_confirmed = distance_to_high > -0.25
    finance_growth_confirmed = (revenue_yoy > 30 or profit_yoy > 30) and gross_margin > 20
    cash_quality_confirmed = ocf_to_or > 0
    disconfirm_triggered = (ret_1y < -0.3 and profit_yoy < 0) or (
        gross_margin > 0 and gross_margin < 10 and profit_yoy < 0
    )
    maturity = maturity_score(ret_1y, ret_2y, relative_strength, distance_to_high)
    crowding = crowding_score(
        ret_60d=metric_float(metrics, "ret_60d"),
        ret_120d=metric_float(metrics, "ret_120d"),
        ret_1y=ret_1y,
        distance_to_high=distance_to_high,
    )
    early = early_signal_score(
        trend_confirmed,
        relative_strength_confirmed,
        finance_growth_confirmed,
        cash_quality_confirmed,
        high_resilience_confirmed,
        maturity,
        crowding,
    )
    score = sum(
        [
            25 if trend_confirmed else 0,
            20 if relative_strength_confirmed else 0,
            20 if finance_growth_confirmed else 0,
            15 if high_resilience_confirmed else 0,
            10 if cash_quality_confirmed else 0,
            10 if ret_2y > 1.0 else 0,
        ]
    )
    if disconfirm_triggered:
        score = min(score, 30)
    metrics["powerlaw_score"] = float(score)
    metrics["early_signal_score"] = float(early)
    metrics["maturity_score"] = float(maturity)
    metrics["crowding_score"] = float(crowding)
    phase = opportunity_phase(early, maturity, crowding, disconfirm_triggered, theme)
    return {
        "trend_confirmed": trend_confirmed,
        "relative_strength_confirmed": relative_strength_confirmed,
        "finance_growth_confirmed": finance_growth_confirmed,
        "cash_quality_confirmed": cash_quality_confirmed,
        "high_resilience_confirmed": high_resilience_confirmed,
        "disconfirm_triggered": disconfirm_triggered,
        "powerlaw_score": float(score),
        "early_signal_score": float(early),
        "maturity_score": float(maturity),
        "crowding_score": float(crowding),
        "opportunity_phase": phase,
        "upgrade_path": upgrade_path(early, disconfirm_triggered, phase, theme),
    }


def build_observation_priority(
    metrics: dict[str, Any],
    evidence: dict[str, Any],
    stock: dict[str, Any],
) -> dict[str, Any]:
    """生成主题内观察优先级，解释先看谁，不代表买卖建议。"""
    verification = evidence.get("verification") if isinstance(evidence.get("verification"), dict) else {}
    if not verification.get("matched") or str(stock.get("verification_status") or "") != "verified":
        return {
            "score": 0.0,
            "grade": "C",
            "reasons": [],
            "gaps": list(verification.get("evidence_gaps") or ["尚未通过入池证据校验。"]),
        }
    theme_fit = metric_float(verification, "theme_fit_score", 75.0)
    early = metric_float(evidence, "early_signal_score")
    powerlaw = metric_float(evidence, "powerlaw_score")
    maturity = metric_float(evidence, "maturity_score")
    crowding = metric_float(evidence, "crowding_score")
    concept_count = len(verification.get("concept_matches") or [])
    concept_bonus = min(10.0, concept_count * 2.0)
    raw = 0.35 * theme_fit + 0.35 * early + 0.20 * powerlaw + concept_bonus - 0.12 * maturity - 0.08 * crowding
    score = float(max(0.0, min(100.0, raw)))
    reasons = [
        f"主题适配 {theme_fit:.0f} 分，说明行业和概念证据与主题匹配。",
        f"早期信号 {early:.0f} 分，来自趋势、相对强弱、财务增长和现金质量。",
    ]
    if concept_count:
        reasons.append(f"概念命中 {concept_count} 个，主题证据更密。")
    if metric_float(metrics, "tr_yoy") > 30 or metric_float(metrics, "netprofit_yoy") > 30:
        reasons.append("财务增长已出现结构化验证。")
    gaps = list(verification.get("evidence_gaps") or [])
    if str(stock.get("theme_id") or "") == "innovative_drug_globalization":
        gaps.extend(["未接入海外收入占比。", "未接入BD授权金额和管线进展。"])
    return {"score": score, "grade": priority_grade(score), "reasons": reasons, "gaps": gaps}


def is_case_study_theme(theme: dict[str, Any] | None) -> bool:
    if not theme:
        return False
    return str(theme.get("status") or "") == "case_study" or "case_study" in str(theme.get("thesis_type") or "")


def is_formal_observation_stock(stock: dict[str, Any]) -> bool:
    """只有来源已验证的正式样本才参与方向排行，避免人工种子污染结论。"""
    return str(stock.get("status") or "") == "active" and str(stock.get("verification_status") or "") == "verified"


def metric_float(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    """读取数值指标，保留 0.0 的真实含义，避免被布尔判断当成缺失。"""
    value = metrics.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def maturity_score(ret_1y: float, ret_2y: float, relative_strength: float, distance_to_high: float) -> float:
    """衡量机会是否已经充分兑现，分数越高越不像早期机会。"""
    score = 0.0
    score += 45 if ret_2y > 2.0 else 0.0
    score += 35 if ret_1y > 1.5 else 20 if ret_1y > 0.8 else 0.0
    score += 15 if relative_strength > 0.8 else 0.0
    score += 10 if distance_to_high > -0.1 and ret_1y > 0.8 else 0.0
    return min(score, 100.0)


def crowding_score(ret_60d: float, ret_120d: float, ret_1y: float, distance_to_high: float) -> float:
    """用价格兑现程度近似拥挤度，避免把已共识行情误当成早期机会。"""
    score = 0.0
    score += 30 if ret_60d > 0.5 else 0.0
    score += 30 if ret_120d > 0.8 else 0.0
    score += 25 if ret_1y > 1.5 else 0.0
    score += 15 if distance_to_high > -0.05 and ret_1y > 0.8 else 0.0
    return min(score, 100.0)


def early_signal_score(
    trend_confirmed: bool,
    relative_strength_confirmed: bool,
    finance_growth_confirmed: bool,
    cash_quality_confirmed: bool,
    high_resilience_confirmed: bool,
    maturity: float,
    crowding: float,
) -> float:
    """衡量“刚起势但未充分兑现”的前瞻机会强度。"""
    raw = sum(
        [
            20 if trend_confirmed else 0,
            20 if relative_strength_confirmed else 0,
            25 if finance_growth_confirmed else 0,
            10 if cash_quality_confirmed else 0,
            10 if high_resilience_confirmed else 0,
            15 if maturity < 55 and crowding < 55 else 0,
        ]
    )
    if maturity >= 55 or crowding >= 55:
        raw = min(raw, 45)
    return float(raw)


def opportunity_phase(
    early_signal: float,
    maturity: float,
    crowding: float,
    disconfirm_triggered: bool,
    theme: dict[str, Any] | None,
) -> str:
    if disconfirm_triggered:
        return "RejectedReview"
    if is_case_study_theme(theme):
        return "CaseStudyLateConfirmed" if maturity >= 55 or crowding >= 55 else "CaseStudyCalibration"
    if maturity >= 75 or crowding >= 75:
        return "LateConfirmed"
    if early_signal >= 75:
        return "EarlyPowerLawCandidate"
    if early_signal >= 55:
        return "Confirming"
    return "Observation"


def upgrade_path(score: float, disconfirm_triggered: bool, phase: str, theme: dict[str, Any] | None) -> str:
    if disconfirm_triggered:
        return "RejectedReview"
    if is_case_study_theme(theme):
        return "CaseStudyCalibration"
    if phase == "LateConfirmed":
        return "DoNotChase"
    if score >= 75:
        return "PaperCandidate"
    if score >= 55:
        return "Confirming"
    return "Observation"


def priority_grade(score: float) -> str:
    if score >= 80:
        return "S"
    if score >= 60:
        return "A"
    if score >= 40:
        return "B"
    return "C"
