import { useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { getReportContent } from "../../entities/report/api";
import type { ReportContent } from "../../entities/report/model";
import { PageHeader } from "../../shared/ui/PageHeader";
import { ReportViewer } from "./components/ReportViewer";

export function ReportsPage() {
  const data = useOutletContext<DashboardContext>();
  const [selected, setSelected] = useState<ReportContent | null>(null);
  const [error, setError] = useState("");
  const reports =
    data.selectedStrategyId === "ALL"
      ? data.reports
      : data.reports.filter((report) => report.strategy_id === data.selectedStrategyId);

  const openReport = (reportId: string) => {
    setError("");
    getReportContent(reportId)
      .then(setSelected)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  };

  return (
    <>
      <PageHeader title="报告" description="统一索引日报、月报、调仓计划和研究报告。" />
      <div className="reports-layout">
        <section className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>标题</th>
                <th>类型</th>
                <th>标签</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((report) => (
                <tr key={report.report_id} className="clickable-row" onClick={() => openReport(report.report_id)}>
                  <td>{report.trade_date}</td>
                  <td>{report.title}</td>
                  <td>{report.report_type}</td>
                  <td>{report.tags.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {reports.length === 0 ? <p className="muted-text">当前策略暂无登记报告</p> : null}
          {error ? <p className="inline-error">{error}</p> : null}
        </section>
        <ReportViewer report={selected} />
      </div>
    </>
  );
}
