import { useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { getStrategy } from "../../entities/strategy/api";
import { strategyMetricText } from "../../entities/strategy/display";
import type { StrategyDefinition } from "../../entities/strategy/model";
import { saveStrategyDraft } from "../../entities/strategyDraft/api";
import { createDraftFactorsFromAvailableFactors } from "../../entities/strategyDraft/factory";
import type { StrategyDraft, StrategyDraftPayload } from "../../entities/strategyDraft/model";
import { validateStrategyDraftWeights } from "../../entities/strategyDraft/validation";
import { formatNumber, formatPercent } from "../../shared/lib/formatters";
import { PageHeader } from "../../shared/ui/PageHeader";

export function StrategiesPage() {
  const data = useOutletContext<DashboardData>();
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyDefinition>(data.strategy);
  const [strategyError, setStrategyError] = useState("");
  const factorWeightTotal = (selectedStrategy.factors ?? []).reduce((total, factor) => total + (factor.weight ?? 0), 0);
  const [drafts, setDrafts] = useState<StrategyDraft[]>(data.strategyDrafts);
  const [draftFactors, setDraftFactors] = useState<StrategyDraftPayload["factors"]>(
    createDraftFactorsFromAvailableFactors(data.factors, selectedStrategy.factors ?? [])
  );
  const [draftName, setDraftName] = useState("Quality Factor Draft");
  const [draftMessage, setDraftMessage] = useState("");
  const validation = useMemo(() => validateStrategyDraftWeights(draftFactors), [draftFactors]);

  function updateDraftFactor(factorId: string, patch: Partial<StrategyDraftPayload["factors"][number]>) {
    setDraftFactors((items) => items.map((item) => (item.factor_id === factorId ? { ...item, ...patch } : item)));
  }

  function handleCloneActiveStrategy() {
    setDraftFactors(createDraftFactorsFromAvailableFactors(data.factors, selectedStrategy.factors ?? []));
    setDraftName(`${selectedStrategy.name} Draft`);
    setDraftMessage("已复制当前生产策略因子组合，可在草案中调整");
  }

  async function openStrategy(strategyId: string) {
    setStrategyError("");
    try {
      setSelectedStrategy(await getStrategy(strategyId));
    } catch (error) {
      setStrategyError(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleSaveDraft() {
    const result = validateStrategyDraftWeights(draftFactors);
    if (!result.valid) {
      setDraftMessage(result.message);
      return;
    }
    const saved = await saveStrategyDraft({
      draft_id: "local_factor_draft",
      name: draftName,
      description: "本地因子组合草案，仅用于研究维护，不进入生产运行。",
      config: { top_n: 20, rebalance: "monthly", source: "frontend_draft" },
      factors: draftFactors
    });
    setDrafts((items) => [saved, ...items.filter((item) => item.draft_id !== saved.draft_id)]);
    setDraftMessage("草案已保存到本地状态库");
  }

  return (
    <>
      <PageHeader title="策略" description="维护策略定义、运行状态、风险层和当前核心指标。" />
      <div className="management-layout">
        <section className="panel table-panel">
          <h2>策略库</h2>
          <table>
            <thead>
              <tr>
                <th>策略</th>
                <th>状态</th>
                <th>类型</th>
                <th>最新日期</th>
                <th>累计收益</th>
                <th>当前回撤</th>
              </tr>
            </thead>
            <tbody>
              {data.strategies.map((item) => {
                const metrics = item.strategy_id === selectedStrategy.strategy_id ? selectedStrategy.latest_metrics : null;
                return (
                  <tr key={item.strategy_id} className="clickable-row" onClick={() => openStrategy(item.strategy_id)}>
                    <td>{item.name}</td>
                    <td>{item.status}</td>
                    <td>{item.strategy_type}</td>
                    <td>{strategyMetricText(metrics, "trade_date")}</td>
                    <td>{strategyMetricText(metrics, "cumulative_return")}</td>
                    <td>{strategyMetricText(metrics, "drawdown")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {strategyError ? <p className="inline-error">{strategyError}</p> : null}
        </section>

        <aside className="panel detail-panel">
          <div className="detail-heading">
            <div>
              <h2>{selectedStrategy.name}</h2>
              <p>{selectedStrategy.description}</p>
            </div>
            <span className={`status ${selectedStrategy.status === "active" ? "success" : "neutral"}`}>{selectedStrategy.status}</span>
          </div>
          <div className="config-grid">
            {Object.entries(selectedStrategy.config ?? {}).map(([key, value]) => (
              <div key={key}>
                <span>{key}</span>
                <strong>{String(value)}</strong>
              </div>
            ))}
            <div>
              <span>factor_weight_total</span>
              <strong>{formatNumber(factorWeightTotal, 3)}</strong>
            </div>
          </div>
          <h2>因子组合</h2>
          <div className="mini-table">
            {(selectedStrategy.factors ?? []).length === 0 ? <p className="muted-text">该策略暂无登记因子组合</p> : null}
            {(selectedStrategy.factors ?? []).map((factor) => (
              <div key={factor.factor_id} className="mini-row">
                <span>{factor.name}</span>
                <strong>{formatPercent(factor.weight)}</strong>
                <em>{factor.transform ?? "-"}</em>
              </div>
            ))}
          </div>
        </aside>
      </div>
      <section className="panel draft-editor">
        <div className="detail-heading">
          <div>
            <h2>本地策略草案</h2>
            <p>用现有因子组合一个研究草案；保存后只进入 SQLite 状态库，不影响每日生产策略。</p>
          </div>
          <span className={`status ${validation.valid ? "success" : "warning"}`}>{validation.message}</span>
        </div>
        <div className="draft-form">
          <label>
            <span>草案名称</span>
            <input value={draftName} onChange={(event) => setDraftName(event.target.value)} />
          </label>
          <button type="button" className="secondary-button" onClick={handleCloneActiveStrategy}>
            复制当前策略
          </button>
          <button type="button" onClick={handleSaveDraft}>
            保存草案
          </button>
        </div>
        {draftMessage ? <p className={validation.valid ? "success-message" : "inline-error"}>{draftMessage}</p> : null}
        <div className="mini-table">
          {draftFactors.map((item) => {
            const factor = data.factors.find((candidate) => candidate.factor_id === item.factor_id);
            return (
              <div key={item.factor_id} className="draft-row">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={item.enabled}
                    onChange={(event) => updateDraftFactor(item.factor_id, { enabled: event.target.checked })}
                  />
                  <span>{factor?.name ?? item.factor_id}</span>
                </label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={item.weight}
                  onChange={(event) => updateDraftFactor(item.factor_id, { weight: Number(event.target.value) })}
                />
                <em>{item.transform}</em>
              </div>
            );
          })}
        </div>
        <h2>已保存草案</h2>
        <div className="mini-table">
          {drafts.length === 0 ? <p className="muted-text">暂无草案</p> : null}
          {drafts.map((draft) => (
            <div key={draft.draft_id} className="mini-row">
              <span>{draft.name}</span>
              <strong>{draft.status}</strong>
              <em>{draft.factors.length} 个因子</em>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
