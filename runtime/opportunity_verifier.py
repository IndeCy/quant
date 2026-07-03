"""机会池候选种子的入池证据校验。"""

from __future__ import annotations

from typing import Any

import duckdb

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


THEME_ALLOWED_INDUSTRIES: dict[str, set[str]] = {
    "ai_optical_module_powerlaw": {"通信设备"},
    "humanoid_robotics_components": {"电气设备", "机械基件", "电器仪表", "汽车配件", "家用电器"},
    "domestic_ai_compute_infrastructure": {"半导体", "IT设备", "通信设备", "软件服务"},
    "semiconductor_equipment_materials": {"半导体"},
    "power_grid_export_upgrade": {"电气设备"},
    "ai_edge_hardware": {"通信设备", "元器件", "软件服务", "半导体"},
    "innovative_drug_globalization": {"化学制药", "生物制药"},
}

THEME_CONCEPT_KEYWORDS: dict[str, list[str]] = {
    "ai_optical_module_powerlaw": ["CPO"],
    "humanoid_robotics_components": ["人形机器人", "机器人执行器", "机器人", "减速器"],
    "domestic_ai_compute_infrastructure": ["算力", "AI芯片"],
    "semiconductor_equipment_materials": ["半导体设备", "半导体材料"],
    "power_grid_export_upgrade": ["电网", "特高压"],
    "ai_edge_hardware": ["消费电子"],
    "innovative_drug_globalization": ["创新药"],
}


def verify_opportunity_seed_stocks(paths: RuntimePaths | None = None) -> dict[str, int]:
    """用本地行业缓存校验候选种子，符合规则才升级为正式观察股。"""
    runtime_paths = paths or get_runtime_paths()
    repository = SystemRepository(runtime_paths.system_state_path)
    industry_rows = _load_industry_map(runtime_paths)
    concept_rows = _load_concept_map(runtime_paths)
    verified_count = 0
    unverified_count = 0
    for theme in repository.list_opportunity_themes():
        allowed = THEME_ALLOWED_INDUSTRIES.get(str(theme["theme_id"]), set())
        for stock in theme.get("stocks", []):
            if not _needs_verification_refresh(stock):
                continue
            evidence = _build_verification_evidence(theme, stock, allowed, industry_rows, concept_rows)
            payload = dict(stock)
            payload["evidence"] = _merge_evidence(stock, evidence)
            if evidence["matched"]:
                payload["status"] = "active"
                payload["source_type"] = "industry_concept_match"
                payload["source_detail"] = evidence["detail"]
                payload["verification_status"] = "verified"
                verified_count += 1
            else:
                payload["status"] = "candidate_seed"
                payload["source_type"] = stock.get("source_type") or "built_in_seed"
                payload["source_detail"] = evidence["detail"]
                payload["verification_status"] = "unverified"
                unverified_count += 1
            repository.upsert_opportunity_stock(payload)
    return {"verified_count": verified_count, "unverified_count": unverified_count}


def _needs_verification_refresh(stock: dict[str, Any]) -> bool:
    status = str(stock.get("status") or "")
    verification_status = str(stock.get("verification_status") or "")
    return status == "candidate_seed" or (status == "active" and verification_status == "verified")


def _load_industry_map(paths: RuntimePaths) -> dict[str, dict[str, str]]:
    industry_path = paths.data_dir / "industry_increment.duckdb"
    if not industry_path.exists():
        return {}
    with duckdb.connect(str(industry_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT ts_code, name, industry
            FROM stock_industry
            """
        ).fetchall()
    return {str(code): {"name": str(name or ""), "industry": str(industry or "")} for code, name, industry in rows}


def _load_concept_map(paths: RuntimePaths) -> dict[tuple[str, str], list[dict[str, str]]]:
    concept_path = paths.data_dir / "opportunity_concept_increment.duckdb"
    if not concept_path.exists():
        return {}
    with duckdb.connect(str(concept_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT theme_id, provider, index_code, index_name, con_code, con_name, keyword
            FROM concept_member
            """
        ).fetchall()
    result: dict[tuple[str, str], list[dict[str, str]]] = {}
    for theme_id, provider, index_code, index_name, con_code, con_name, keyword in rows:
        result.setdefault((str(theme_id), str(con_code)), []).append(
            {
                "provider": str(provider),
                "index_code": str(index_code),
                "index_name": str(index_name),
                "con_name": str(con_name or ""),
                "keyword": str(keyword),
            }
        )
    return result


def _build_verification_evidence(
    theme: dict[str, Any],
    stock: dict[str, Any],
    allowed_industries: set[str],
    industry_rows: dict[str, dict[str, str]],
    concept_rows: dict[tuple[str, str], list[dict[str, str]]],
) -> dict[str, Any]:
    theme_id = str(theme.get("theme_id") or "")
    symbol = str(stock.get("symbol") or "")
    row = industry_rows.get(symbol, {})
    industry = str(row.get("industry") or "")
    concept_matches = concept_rows.get((theme_id, symbol), [])
    if _is_case_study_theme(theme):
        return {
            "matched": False,
            "reason": "case_study_theme",
            "industry": industry,
            "concept_matches": concept_matches,
            "allowed_industries": sorted(allowed_industries),
            "detail": "历史校准案例不升级为正式观察池。",
        }
    if not industry:
        return {
            "matched": False,
            "reason": "industry_missing",
            "industry": "",
            "concept_matches": concept_matches,
            "allowed_industries": sorted(allowed_industries),
            "detail": f"{symbol} 未在 Tushare 行业缓存中找到行业证据。",
        }
    industry_matched = industry in allowed_industries
    concept_matched = bool(concept_matches)
    matched = industry_matched and concept_matched
    if matched:
        reason = "industry_and_concept_matched"
    elif not industry_matched:
        reason = "industry_mismatch"
    else:
        reason = "concept_missing"
    explanation = _build_theme_fit_explanation(industry, industry_matched, allowed_industries, concept_matches)
    return {
        "matched": matched,
        "reason": reason,
        "industry": industry,
        "concept_matches": concept_matches,
        "allowed_industries": sorted(allowed_industries),
        "theme_fit_score": explanation["score"],
        "theme_fit_grade": explanation["grade"],
        "selection_reasons": explanation["selection_reasons"],
        "evidence_gaps": explanation["evidence_gaps"],
        "detail": f"Tushare 行业={industry}，概念命中={len(concept_matches)}，主题={theme_id}，允许行业={','.join(sorted(allowed_industries)) or '-'}。",
    }


def _merge_evidence(stock: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(stock.get("evidence") or {})
    evidence["verification"] = verification
    return evidence


def _is_case_study_theme(theme: dict[str, Any]) -> bool:
    return str(theme.get("status") or "") == "case_study" or "case_study" in str(theme.get("thesis_type") or "")


def _build_theme_fit_explanation(
    industry: str,
    industry_matched: bool,
    allowed_industries: set[str],
    concept_matches: list[dict[str, str]],
) -> dict[str, Any]:
    """生成主题适配解释，说明入池依据而不是预测收益。"""
    reasons: list[str] = []
    gaps: list[str] = []
    score = 0.0
    if industry_matched:
        score += 40.0
        reasons.append(f"行业证据: Tushare stock_basic 行业为 {industry}，属于主题允许行业。")
    else:
        gaps.append(f"行业不匹配: 当前行业为 {industry or '缺失'}，允许行业为 {','.join(sorted(allowed_industries)) or '-'}。")
    if concept_matches:
        index_names = sorted({item["index_name"] for item in concept_matches if item.get("index_name")})
        providers = sorted({item["provider"] for item in concept_matches if item.get("provider")})
        keywords = sorted({item["keyword"] for item in concept_matches if item.get("keyword")})
        score += 35.0
        score += min(15.0, max(0, len(index_names) - 1) * 5.0)
        score += 5.0 if len(providers) >= 2 else 0.0
        score += 5.0 if len(keywords) >= 2 else 0.0
        reasons.append(f"概念证据: 命中 {','.join(index_names[:6])}。")
    else:
        gaps.append("缺少主题概念成分证据。")
    score = min(100.0, score)
    return {
        "score": score,
        "grade": _theme_fit_grade(score),
        "selection_reasons": reasons,
        "evidence_gaps": gaps,
    }


def _theme_fit_grade(score: float) -> str:
    if score >= 90:
        return "S"
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    return "C"
