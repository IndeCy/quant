import type { ReportIndex } from "../../../entities/report/model";

export function RecentReportsPanel({ reports }: { reports: ReportIndex[] }) {
  return (
    <section className="panel compact">
      <h2>报告索引</h2>
      {reports.slice(0, 6).map((report) => (
        <div className="list-row" key={report.report_id}>
          <span>{report.title}</span>
          <strong>{report.trade_date}</strong>
        </div>
      ))}
    </section>
  );
}
