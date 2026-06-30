import { useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { getReportContent } from "../../entities/report/api";
import type { ReportContent } from "../../entities/report/model";
import { getRunDetail } from "../../entities/run/api";
import { runArtifactTypeLabel } from "../../entities/run/artifact";
import type { StrategyRunDetail } from "../../entities/run/model";
import { runStepTone } from "../../entities/run/status";
import { PageHeader } from "../../shared/ui/PageHeader";
import { ReportViewer } from "../reports/components/ReportViewer";

export function RunsPage() {
  const data = useOutletContext<DashboardContext>();
  const [detail, setDetail] = useState<StrategyRunDetail | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<ReportContent | null>(null);
  const [error, setError] = useState("");
  const runs = data.selectedStrategyId === "ALL" ? data.runs : data.runs.filter((run) => run.strategy_id === data.selectedStrategyId);

  const openRun = (strategyId: string, tradeDate: string) => {
    setError("");
    setSelectedArtifact(null);
    getRunDetail(strategyId, tradeDate)
      .then(setDetail)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  };

  const openArtifact = (reportId: string) => {
    setError("");
    getReportContent(reportId)
      .then(setSelectedArtifact)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  };

  return (
    <>
      <PageHeader title="运行" description="查看每日流水线运行状态、运行目录和失败信息。" />
      <div className="runs-layout">
        <section className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>策略</th>
                <th>状态</th>
                <th>信息</th>
                <th>目录</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={`${run.strategy_id}-${run.trade_date}`} className="clickable-row" onClick={() => openRun(run.strategy_id, run.trade_date)}>
                  <td>{run.trade_date}</td>
                  <td>{run.strategy_id}</td>
                  <td>{run.status}</td>
                  <td>{run.message || "-"}</td>
                  <td>{run.run_dir}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs.length === 0 ? <p className="muted-text">当前策略暂无运行记录</p> : null}
          {error ? <p className="inline-error">{error}</p> : null}
        </section>
        <div className="detail-panel">
          <RunDetailPanel detail={detail} onOpenArtifact={openArtifact} />
          <ReportViewer report={selectedArtifact} />
        </div>
      </div>
    </>
  );
}

function RunDetailPanel({
  detail,
  onOpenArtifact
}: {
  detail: StrategyRunDetail | null;
  onOpenArtifact: (reportId: string) => void;
}) {
  if (!detail) {
    return (
      <section className="panel run-detail empty-viewer">
        <span>选择左侧运行记录查看步骤</span>
      </section>
    );
  }
  return (
    <section className="panel run-detail">
      <div className="viewer-header">
        <div>
          <h2>{detail.run.trade_date}</h2>
          <p>{detail.run.run_dir}</p>
        </div>
        <span>{detail.run.status}</span>
      </div>
      <div className="step-list">
        {detail.steps.map((step) => (
          <div className="step-row" key={step.step_name}>
            <span className={`step-dot ${runStepTone(step.status)}`} />
            <div>
              <strong>{step.step_name}</strong>
              <p>{step.message || "-"}</p>
              {step.artifact_path ? <small>{step.artifact_path}</small> : null}
            </div>
            <em>{step.status}</em>
          </div>
        ))}
      </div>
      <h2>运行产物</h2>
      <div className="mini-table">
        {detail.artifacts.length === 0 ? <p className="muted-text">暂无登记产物</p> : null}
        {detail.artifacts.map((artifact) => (
          <button className="mini-row artifact-row artifact-button" key={artifact.report_id} type="button" onClick={() => onOpenArtifact(artifact.report_id)}>
            <span>{artifact.title}</span>
            <strong>{runArtifactTypeLabel(artifact.report_type)}</strong>
            <em>{artifact.file_path}</em>
          </button>
        ))}
      </div>
    </section>
  );
}
