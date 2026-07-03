import { lifecycleTone, transitionCandidates } from "../../entities/strategy/lifecycle";
import type { StrategyInstance } from "../../entities/strategy/model";

interface StrategyOperationsPanelProps {
  selectedInstance: StrategyInstance | null;
  onTransition: (instance: StrategyInstance, targetStatus: string) => void;
}

export function StrategyOperationsPanel({ selectedInstance, onTransition }: StrategyOperationsPanelProps) {
  const candidates = transitionCandidates(selectedInstance?.status ?? "draft");

  return (
    <section className="panel draft-editor">
      <div className="detail-heading">
        <div>
          <h2>运行控制台</h2>
          <p>按策略实例查看生命周期、每日运行开关、账户快照和实际偏离。这里不修改 Alpha，只管理运行状态。</p>
        </div>
        <span className={`status ${lifecycleTone(selectedInstance?.status ?? "draft")}`}>{selectedInstance?.status ?? "无实例"}</span>
      </div>
      {selectedInstance ? (
        <>
          <div className="config-grid">
            <div>
              <span>策略实例</span>
              <strong>{selectedInstance.name}</strong>
            </div>
            <div>
              <span>每日自动运行</span>
              <strong>{selectedInstance.enabled ? "开启" : "关闭"}</strong>
            </div>
            <div>
              <span>基准</span>
              <strong>{selectedInstance.benchmark}</strong>
            </div>
            <div>
              <span>风险层</span>
              <strong>{selectedInstance.risk_overlay}</strong>
            </div>
          </div>
          <div className="lifecycle-actions">
            {candidates.length === 0 ? <p className="muted-text">当前状态没有可执行流转动作</p> : null}
            {candidates.map((candidate) => (
              <button key={candidate.target_status} type="button" onClick={() => onTransition(selectedInstance, candidate.target_status)}>
                {candidate.label}
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="muted-text">暂无策略实例</p>
      )}
    </section>
  );
}
