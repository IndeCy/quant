import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { getFactor, saveFactor } from "../../entities/factor/api";
import type { FactorDefinition } from "../../entities/factor/model";
import { factorUsageLabel, factorWeightSum } from "../../entities/factor/usage";
import { formatNumber, formatPercent } from "../../shared/lib/formatters";
import { PageHeader } from "../../shared/ui/PageHeader";

export function FactorsPage() {
  const data = useOutletContext<DashboardContext>();
  const [factors, setFactors] = useState(data.factors);
  const [selectedFactorId, setSelectedFactorId] = useState(data.factors[0]?.factor_id ?? "");
  const [selectedFactor, setSelectedFactor] = useState<FactorDefinition | null>(null);
  const [factorId, setFactorId] = useState("profit_stability");
  const [factorName, setFactorName] = useState("盈利稳定性");
  const [factorDescription, setFactorDescription] = useState("过去三年ROA波动率越低越好，需后续补充因子分数。");
  const [factorMessage, setFactorMessage] = useState("");
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
    () => selectedFactor ?? factors.find((factor) => factor.factor_id === selectedFactorId) ?? factors[0],
    [factors, selectedFactor, selectedFactorId]
  );

  async function handleSaveFactor() {
    const saved = await saveFactor({
      factor_id: factorId,
      name: factorName,
      category: "custom",
      direction: "unknown",
      source: "manual",
      description: factorDescription,
      enabled: true,
      config: { as_of_field: "manual_confirm_required" },
      strategies: []
    });
    setFactors((items) => [saved, ...items.filter((item) => item.factor_id !== saved.factor_id)]);
    setSelectedFactorId(saved.factor_id);
    setSelectedFactor(saved);
    setFactorMessage("因子定义已保存，可在策略实例工厂中组合使用");
    await data.refreshData();
  }

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
              {factors.map((factor) => (
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
      <section className="panel draft-editor">
        <div className="detail-heading">
          <div>
            <h2>正式因子登记</h2>
            <p>把已结构化的外部因子沉淀到因子库。这里只保存元数据，不自动生成因子分数。</p>
          </div>
          <span className="status neutral">manual</span>
        </div>
        <div className="idea-grid">
          <div className="idea-form">
            <label>
              <span>因子ID</span>
              <input value={factorId} onChange={(event) => setFactorId(event.target.value)} />
            </label>
            <label>
              <span>因子名称</span>
              <input value={factorName} onChange={(event) => setFactorName(event.target.value)} />
            </label>
          </div>
          <div className="idea-form">
            <label>
              <span>因子说明</span>
              <textarea value={factorDescription} onChange={(event) => setFactorDescription(event.target.value)} />
            </label>
            <button type="button" onClick={handleSaveFactor}>
              保存到因子库
            </button>
          </div>
        </div>
        {factorMessage ? <p className="success-message">{factorMessage}</p> : null}
      </section>
    </>
  );
}
