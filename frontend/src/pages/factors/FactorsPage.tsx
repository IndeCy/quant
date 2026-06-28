import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { getFactor } from "../../entities/factor/api";
import type { FactorDefinition } from "../../entities/factor/model";
import { factorUsageLabel, factorWeightSum } from "../../entities/factor/usage";
import { formatNumber, formatPercent } from "../../shared/lib/formatters";
import { PageHeader } from "../../shared/ui/PageHeader";

export function FactorsPage() {
  const data = useOutletContext<DashboardData>();
  const [selectedFactorId, setSelectedFactorId] = useState(data.factors[0]?.factor_id ?? "");
  const [selectedFactor, setSelectedFactor] = useState<FactorDefinition | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!selectedFactorId) {
      setSelectedFactor(null);
      return;
    }
    let active = true;
    setError("");
    getFactor(selectedFactorId)
      .then((factor) => {
        if (active) {
          setSelectedFactor(factor);
        }
      })
      .catch((reason: Error) => {
        if (active) {
          setSelectedFactor(null);
          setError(reason.message);
        }
      });
    return () => {
      active = false;
    };
  }, [selectedFactorId]);

  const detail = useMemo(
    () => selectedFactor ?? data.factors.find((factor) => factor.factor_id === selectedFactorId) ?? data.factors[0],
    [data.factors, selectedFactor, selectedFactorId]
  );

  return (
    <>
      <PageHeader title="因子" description="查看可组合因子库、因子方向、as-of 来源和启用状态。" />
      <div className="management-layout">
        <section className="panel table-panel">
          <h2>因子库</h2>
          <table>
            <thead>
              <tr>
                <th>因子</th>
                <th>分类</th>
                <th>方向</th>
                <th>来源</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {data.factors.map((factor) => (
                <tr
                  key={factor.factor_id}
                  className="clickable-row"
                  onClick={() => setSelectedFactorId(factor.factor_id)}
                >
                  <td>{factor.name}</td>
                  <td>{factor.category}</td>
                  <td>{factor.direction}</td>
                  <td>{factor.source ?? "-"}</td>
                  <td>{factor.enabled ? "启用" : "停用"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <aside className="panel detail-panel">
          {detail ? (
            <>
              <div className="detail-heading">
                <div>
                  <h2>{detail.name}</h2>
                  <p>{detail.description ?? detail.factor_id}</p>
                </div>
                <span className={`status ${detail.enabled ? "success" : "neutral"}`}>
                  {detail.enabled ? "启用" : "停用"}
                </span>
              </div>
              {error ? <p className="inline-error">{error}</p> : null}
              <div className="config-grid">
                <div>
                  <span>使用状态</span>
                  <strong>{factorUsageLabel(detail)}</strong>
                </div>
                <div>
                  <span>启用权重合计</span>
                  <strong>{formatNumber(factorWeightSum(detail), 3)}</strong>
                </div>
                {Object.entries(detail.config ?? {}).map(([key, value]) => (
                  <div key={key}>
                    <span>{key}</span>
                    <strong>{String(value)}</strong>
                  </div>
                ))}
              </div>
              <h2>策略使用关系</h2>
              <div className="mini-table">
                {(detail.strategies ?? []).map((strategy) => (
                  <div key={strategy.strategy_id} className="mini-row">
                    <span>{strategy.name}</span>
                    <strong>{formatPercent(strategy.weight)}</strong>
                    <em>{strategy.transform}</em>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="inline-error">暂无因子定义</p>
          )}
        </aside>
      </div>
    </>
  );
}
