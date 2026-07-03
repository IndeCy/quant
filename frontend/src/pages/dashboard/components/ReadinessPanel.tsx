import type { ReadinessReport } from "../../../entities/readiness/model";
import { readinessCheckLabel, readinessTitle, readinessTone } from "../../../entities/readiness/status";

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
              <strong>{readinessCheckLabel(check.name)}</strong>
              <p>{check.message}</p>
            </div>
            <em>{check.status}</em>
          </div>
        ))}
      </div>
    </section>
  );
}
