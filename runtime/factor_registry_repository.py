"""Factor Registry V2 仓库方法。"""

from __future__ import annotations

import json
from typing import Any


FINANCIAL_SOURCES = {"fina_indicator", "income", "balancesheet", "cashflow", "forecast", "express"}


class FactorRegistryRepositoryMixin:
    """保存因子契约，支撑因子自由组合和时点安全检查。"""

    def upsert_factor_contract(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """登记因子 V2 契约，并同步基础因子表。"""
        payload = {**dict(payload or {}), **kwargs}
        factor_id = str(payload.get("factor_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        category = str(payload.get("category") or "").strip()
        direction = str(payload.get("direction") or "").strip()
        source = str(payload.get("source") or "").strip()
        if not all([factor_id, name, category, direction, source]):
            raise ValueError("factor_id, name, category, direction and source are required")
        _validate_as_of(source, str(payload.get("as_of_policy") or ""), str(payload.get("as_of_field") or ""))
        config = dict(payload.get("config") or {})
        if payload.get("as_of_field"):
            config["as_of_field"] = str(payload["as_of_field"])
        self.upsert_factor(
            factor_id=factor_id,
            name=name,
            category=category,
            direction=direction,
            source=source,
            description=str(payload.get("description") or ""),
            enabled=str(payload.get("status") or "active") != "disabled",
            config=config,
        )
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO factor_contracts(
                    factor_id, version, status, frequency, value_type,
                    as_of_policy, as_of_field, effective_date_field, lag_days,
                    input_datasets_json, input_fields_json, output_fields_json,
                    dependencies_json, validation_json, owner
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(factor_id) DO UPDATE SET
                    version=excluded.version,
                    status=excluded.status,
                    frequency=excluded.frequency,
                    value_type=excluded.value_type,
                    as_of_policy=excluded.as_of_policy,
                    as_of_field=excluded.as_of_field,
                    effective_date_field=excluded.effective_date_field,
                    lag_days=excluded.lag_days,
                    input_datasets_json=excluded.input_datasets_json,
                    input_fields_json=excluded.input_fields_json,
                    output_fields_json=excluded.output_fields_json,
                    dependencies_json=excluded.dependencies_json,
                    validation_json=excluded.validation_json,
                    owner=excluded.owner,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    factor_id,
                    str(payload.get("version") or "v1"),
                    str(payload.get("status") or "draft"),
                    str(payload.get("frequency") or ""),
                    str(payload.get("value_type") or ""),
                    str(payload.get("as_of_policy") or ""),
                    str(payload.get("as_of_field") or ""),
                    str(payload.get("effective_date_field") or ""),
                    int(payload.get("lag_days") or 0),
                    json.dumps(list(payload.get("input_datasets") or []), ensure_ascii=False, sort_keys=True),
                    json.dumps(list(payload.get("input_fields") or []), ensure_ascii=False, sort_keys=True),
                    json.dumps(list(payload.get("output_fields") or []), ensure_ascii=False, sort_keys=True),
                    json.dumps(list(payload.get("dependencies") or []), ensure_ascii=False, sort_keys=True),
                    json.dumps(dict(payload.get("validation") or {}), ensure_ascii=False, sort_keys=True),
                    str(payload.get("owner") or ""),
                ],
            )
            row = con.execute("SELECT * FROM factor_contracts WHERE factor_id = ?", [factor_id]).fetchone()
        return _parse_contract(row)

    def load_factor_contract(self, factor_id: str) -> dict[str, Any] | None:
        """读取单个因子契约，并合并基础因子信息。"""
        with self._connect() as con:
            contract = con.execute("SELECT * FROM factor_contracts WHERE factor_id = ?", [factor_id]).fetchone()
        if contract is None:
            return None
        result = _parse_contract(contract)
        definition = self.load_factor_definition(factor_id)
        if definition:
            result.update(
                {
                    "name": definition["name"],
                    "category": definition["category"],
                    "direction": definition["direction"],
                    "source": definition["source"],
                    "description": definition["description"],
                    "enabled": definition["enabled"],
                }
            )
        return result

    def list_factor_contracts(self) -> list[dict[str, Any]]:
        """读取全部因子契约。"""
        with self._connect() as con:
            rows = con.execute("SELECT * FROM factor_contracts ORDER BY factor_id").fetchall()
        return [_parse_contract(row) for row in rows]

    def validate_strategy_factor_contracts(self, strategy_id: str) -> dict[str, Any]:
        """检查策略实例引用的因子是否都有 V2 契约。"""
        strategy = self.load_strategy_instance(strategy_id)
        factor_ids = sorted({str(item.get("factor_id")) for item in strategy.get("factors", []) if item.get("factor_id")})
        contracts = {item["factor_id"] for item in self.list_factor_contracts()}
        missing = [factor_id for factor_id in factor_ids if factor_id not in contracts]
        covered = [factor_id for factor_id in factor_ids if factor_id in contracts]
        return {
            "strategy_id": strategy_id,
            "status": "PASS" if not missing else "FAIL",
            "covered_factors": covered,
            "missing_factors": missing,
        }


def _validate_as_of(source: str, as_of_policy: str, as_of_field: str) -> None:
    """财务源必须声明公告日字段，避免未来函数。"""
    if source in FINANCIAL_SOURCES and as_of_policy == "financial_announcement" and not as_of_field:
        raise ValueError("as_of_field is required for financial factors")


def _parse_contract(row: Any) -> dict[str, Any]:
    """解析契约 JSON 字段。"""
    result = dict(row)
    for key in ["input_datasets", "input_fields", "output_fields", "dependencies"]:
        result[key] = json.loads(result.pop(f"{key}_json") or "[]")
    result["validation"] = json.loads(result.pop("validation_json") or "{}")
    return result
