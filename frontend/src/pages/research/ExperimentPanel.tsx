import { Archive, ChevronDown, FlaskConical, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getExperiment } from "../../entities/experiment/api";
import { groupExperiments } from "../../entities/experiment/display";
import type { ExperimentDetail, ExperimentSummary } from "../../entities/experiment/model";

interface ExperimentPanelProps {
  experiments: ExperimentSummary[];
}

export function ExperimentPanel({ experiments }: ExperimentPanelProps) {
  const experimentGroups = groupExperiments(experiments);
  const [selectedId, setSelectedId] = useState(
    experimentGroups.active[0]?.experiment_id ?? experimentGroups.archived[0]?.experiment_id ?? ""
  );
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadDetail = useCallback(async (experimentId: string) => {
    if (!experimentId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setDetail(await getExperiment(experimentId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "实验详情加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const available = experiments.some((item) => item.experiment_id === selectedId);
    const nextId = available
      ? selectedId
      : experimentGroups.active[0]?.experiment_id ?? experimentGroups.archived[0]?.experiment_id ?? "";
    if (nextId !== selectedId) {
      setSelectedId(nextId);
    }
    void loadDetail(nextId);
  }, [experiments, loadDetail, selectedId]);

  const latestMetrics = detail?.latest_run?.metrics ?? detail?.latest_metrics ?? {};
  const gate = objectMetric(latestMetrics, "gate");
  const dataset = objectMetric(latestMetrics, "dataset");
  const gateStatus = detail?.latest_run?.outcome || textMetric(gate, "status") || "未评估";
  const preview = findSummaryPreview(detail);

  function selectExperiment(experimentId: string) {
    setSelectedId(experimentId);
  }

  return (
    <section className="panel experiment-panel">
      <div className="detail-heading">
        <div>
          <h2>研究尝试资产</h2>
          <p>当前研究优先展示；已拒绝、失败或退役的尝试收进归档，相同计算默认复用历史结果。</p>
        </div>
        <span className="status neutral">
          {experimentGroups.active.length} 当前 · {experimentGroups.archived.length} 归档
        </span>
      </div>
      {experiments.length === 0 ? <p className="muted-text">暂无已运行实验</p> : null}
      <div className="experiment-layout">
        <div className="experiment-list" aria-label="研究实验列表">
          {experimentGroups.active.length === 0 ? <p className="muted-text">暂无当前研究</p> : null}
          {experimentGroups.active.map((item) => experimentRow(item, selectedId, selectExperiment))}
          {experimentGroups.archived.length > 0 ? (
            <div className="experiment-archive">
              <button
                className="experiment-archive-toggle"
                type="button"
                aria-expanded={archiveOpen}
                onClick={() => setArchiveOpen((open) => !open)}
              >
                <Archive size={16} aria-hidden="true" />
                <span>失败归档</span>
                <small>{experimentGroups.archived.length} 项</small>
                <ChevronDown className={archiveOpen ? "open" : ""} size={16} aria-hidden="true" />
              </button>
              {archiveOpen ? (
                <div className="experiment-archive-list" aria-label="失败研究归档列表">
                  {experimentGroups.archived.map((item) => experimentRow(item, selectedId, selectExperiment))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="experiment-detail">
          {loading ? (
            <div className="experiment-loading"><RefreshCw size={16} />正在加载实验资产</div>
          ) : null}
          {error ? <p className="inline-error">{error}</p> : null}
          {!loading && detail ? (
            <>
              <div className="viewer-header">
                <div>
                  <h2>{detail.name}</h2>
                  <p>{detail.description}</p>
                </div>
                <span className={`status ${gateTone(gateStatus)}`}>{gateStatus}</span>
              </div>
              <div className="config-grid experiment-metrics">
                <div>
                  <span>研究结论</span>
                  <strong>{gateStatus}</strong>
                </div>
                <div>
                  <span>数据截止</span>
                  <strong>{detail.latest_run?.data_as_of || detail.latest_data_as_of || "-"}</strong>
                </div>
                <div>
                  <span>定义指纹</span>
                  <strong title={detail.definition_fingerprint}>{shortHash(detail.definition_fingerprint)}</strong>
                </div>
                <div>
                  <span>避免重复计算</span>
                  <strong>{detail.latest_run?.reuse_count ?? detail.latest_reuse_count ?? 0} 次</strong>
                </div>
                <div>
                  <span>历史运行</span>
                  <strong>{detail.runs.length} 次</strong>
                </div>
                <div>
                  <span>{textMetric(latestMetrics, "selected_model_id") ? "选定模型" : "数据集哈希"}</span>
                  <strong title={textMetric(dataset, "dataset_hash")}>
                    {textMetric(latestMetrics, "selected_model_id") || shortHash(textMetric(dataset, "dataset_hash"))}
                  </strong>
                </div>
              </div>
              {detail.latest_run?.decision_reason ? (
                <p className="experiment-decision">{detail.latest_run.decision_reason}</p>
              ) : null}
              <div className="experiment-gates">
                {Object.entries(objectMetric(gate, "checks")).map(([name, passed]) => (
                  <span key={name} className={`status ${passed === true ? "success" : "danger"}`}>
                    {gateLabel(name)} {passed === true ? "PASS" : "FAIL"}
                  </span>
                ))}
              </div>
              {preview ? <pre className="experiment-report-preview">{preview}</pre> : <p className="muted-text">暂无可预览的实验报告</p>}
              <div className="experiment-history">
                <h3>运行历史</h3>
                {detail.runs.map((run) => (
                  <div className="experiment-history-row" key={run.run_id}>
                    <span>{run.run_date}</span>
                    <span>{run.data_as_of || "-"}</span>
                    <span className={`status ${gateTone(run.outcome || run.status)}`}>
                      {run.outcome || run.status}
                    </span>
                    <span title={run.run_fingerprint}>{shortHash(run.run_fingerprint)}</span>
                    <span>复用 {run.reuse_count} 次</span>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function experimentRow(
  item: ExperimentSummary,
  selectedId: string,
  selectExperiment: (experimentId: string) => void
) {
  const itemGate = objectMetric(item.latest_metrics, "gate");
  const itemStatus = item.latest_outcome || textMetric(itemGate, "status") || item.latest_run_status || item.status;
  return (
    <button
      key={item.experiment_id}
      className={`experiment-list-row ${item.experiment_id === selectedId ? "selected-row" : ""}`}
      type="button"
      onClick={() => selectExperiment(item.experiment_id)}
    >
      <FlaskConical size={16} aria-hidden="true" />
      <span>
        <strong>{item.name}</strong>
        <small>{item.latest_run_date || "尚未运行"}</small>
      </span>
      <em className={`status ${gateTone(itemStatus)}`}>{itemStatus}</em>
    </button>
  );
}

function objectMetric(source: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = source[key];
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function textMetric(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  return typeof value === "string" ? value : "";
}

function shortHash(value: string): string {
  return value ? `${value.slice(0, 12)}...` : "-";
}

function gateTone(status: string): string {
  if (status === "PASS" || status === "SUCCESS" || status === "completed") {
    return "success";
  }
  if (status === "FAIL" || status === "FAILED" || status === "REJECTED") {
    return "danger";
  }
  return "neutral";
}

function gateLabel(name: string): string {
  const labels: Record<string, string> = {
    test_rank_ic: "RankIC",
    positive_ic_months: "正 IC 月份",
    after_cost_sharpe: "费后 Sharpe",
    drawdown: "回撤",
    turnover: "换手"
  };
  return labels[name] ?? name;
}

function findSummaryPreview(detail: ExperimentDetail | null): string {
  const artifacts = detail?.latest_run?.artifacts ?? [];
  const report = artifacts.find((item) => item.artifact_type === "summary" && item.preview);
  return report?.preview ?? artifacts.find((item) => item.preview)?.preview ?? "";
}
