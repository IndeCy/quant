import type { ReadinessReport } from "../../../entities/readiness/model";
import { readinessTitle, readinessTone } from "../../../entities/readiness/status";

const checkLabels: Record<string, string> = {
  tushare_token: "Tushare Token",
  live_market_data: "行情增量数据",
  benchmark_data: "基准数据",
  monitoring_db: "监控库",
  system_state_db: "系统状态库",
  scheduler_job: "每日任务",
  api_service: "API 服务",
  frontend_service: "前端服务",
  scheduler_service: "调度器服务"
};

export function ReadinessPanel({ report }: { report: ReadinessReport }) {
  return (
    <section className="panel compact readiness-panel">
      <div className="panel-title-row">
        <h2>生产就绪度</h2>
        <span className={`status ${readinessTone(report.status)}`}>{readinessTitle(report.status)}</span>
      </div>
      <div className="step-list">
        {report.checks.map((check) => (
          <div className="step-row" key={check.name}>
            <span className={`step-dot ${check.status === "PASS" ? "success" : "danger"}`} />
            <div>
              <strong>{checkLabels[check.name] ?? check.name}</strong>
              <p>{check.message}</p>
            </div>
            <em>{check.status}</em>
          </div>
        ))}
      </div>
    </section>
  );
}
