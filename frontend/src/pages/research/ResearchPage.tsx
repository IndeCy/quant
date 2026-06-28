import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { PageHeader } from "../../shared/ui/PageHeader";

export function ResearchPage() {
  const data = useOutletContext<DashboardData>();
  const todos = data.researchTodos;
  const researchReports = data.reports.filter((report) => report.tags.includes("research") || report.report_type.includes("research"));

  return (
    <>
      <PageHeader title="研究" description="集中维护非紧急研究、Agent 分析入口和可回溯研究材料。" />
      <div className="research-grid">
        <section className="panel detail-panel">
          <div className="detail-heading">
            <div>
              <h2>Agent 分析入口</h2>
              <p>这里沉淀研究任务，Agent 后续从待办资料库领取，不直接影响生产策略和每日流水线。</p>
            </div>
            <span className="status neutral">只读</span>
          </div>
          <div className="config-grid">
            <div>
              <span>策略草案</span>
              <strong>{data.strategyDrafts.length}</strong>
            </div>
            <div>
              <span>研究报告</span>
              <strong>{researchReports.length}</strong>
            </div>
            <div>
              <span>待办来源</span>
              <strong>{todos.missing ? "缺失" : "已加载"}</strong>
            </div>
            <div>
              <span>生产隔离</span>
              <strong>不触发调仓</strong>
            </div>
          </div>
          <div className="path-block">
            <span>资料库路径</span>
            <code>{todos.path}</code>
          </div>
        </section>

        <section className="panel detail-panel">
          <div className="detail-heading">
            <div>
              <h2>研究报告索引</h2>
              <p>报告中心仍是统一文件入口；这里仅聚合带 research 标签的材料。</p>
            </div>
          </div>
          <div className="mini-table">
            {researchReports.length === 0 ? <p className="muted-text">暂无 research 标签报告</p> : null}
            {researchReports.map((report) => (
              <div key={report.report_id} className="mini-row">
                <span>{report.title}</span>
                <strong>{report.trade_date}</strong>
                <em>{report.report_type}</em>
              </div>
            ))}
          </div>
        </section>
      </div>
      <section className="panel research-todos">
        <div className="detail-heading">
          <div>
            <h2>{todos.title}</h2>
            <p>这些是已沉淀但不立即执行的研究方向。</p>
          </div>
        </div>
        <pre>{todos.content}</pre>
      </section>
    </>
  );
}
