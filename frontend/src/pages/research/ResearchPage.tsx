import { useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { saveFactorIdea, saveStrategyIdea } from "../../entities/research/api";
import { PageHeader } from "../../shared/ui/PageHeader";

export function ResearchPage() {
  const data = useOutletContext<DashboardContext>();
  const todos = data.researchTodos;
  const [factorIdeas, setFactorIdeas] = useState(data.factorIdeas);
  const [strategyIdeas, setStrategyIdeas] = useState(data.strategyIdeas);
  const [factorTitle, setFactorTitle] = useState("盈利稳定性");
  const [factorText, setFactorText] = useState("过去三年ROA或ROE波动率越低越好，必须按财报披露日as-of。");
  const [strategyTitle, setStrategyTitle] = useState("质量现金流组合");
  const [strategyText, setStrategyText] = useState("使用ROA和OCF_TO_OR组合，月频Top20，进入paper观察。");
  const [message, setMessage] = useState("");
  const researchReports = data.reports.filter((report) => report.tags.includes("research") || report.report_type.includes("research"));

  async function handleSaveFactorIdea() {
    const ideaId = `factor_${Date.now()}`;
    const saved = await saveFactorIdea({
      idea_id: ideaId,
      title: factorTitle,
      raw_description: factorText,
      source: "manual_input",
      hypothesis: factorText,
      required_data: [],
      as_of_requirement: "需要人工确认是否依赖财报披露日",
      direction: "unknown",
      status: "draft"
    });
    setFactorIdeas((items) => [saved, ...items]);
    setMessage("因子想法已保存到研究资料库");
    await data.refreshData();
  }

  async function handleSaveStrategyIdea() {
    const ideaId = `strategy_${Date.now()}`;
    const saved = await saveStrategyIdea({
      idea_id: ideaId,
      title: strategyTitle,
      raw_description: strategyText,
      source: "manual_input",
      hypothesis: strategyText,
      candidate_template: "factor_topn_monthly",
      required_factors: [],
      status: "draft"
    });
    setStrategyIdeas((items) => [saved, ...items]);
    setMessage("策略想法已保存到研究资料库");
    await data.refreshData();
  }

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
      <section className="panel draft-editor">
        <div className="detail-heading">
          <div>
            <h2>外部想法录入</h2>
            <p>先把自然语言想法存成研究资产，不直接进入生产运行；后续再结构化为因子或策略实例。</p>
          </div>
          <span className="status neutral">manual</span>
        </div>
        <div className="idea-grid">
          <div className="idea-form">
            <h2>因子想法</h2>
            <label>
              <span>标题</span>
              <input value={factorTitle} onChange={(event) => setFactorTitle(event.target.value)} />
            </label>
            <label>
              <span>描述</span>
              <textarea value={factorText} onChange={(event) => setFactorText(event.target.value)} />
            </label>
            <button type="button" onClick={handleSaveFactorIdea}>
              保存因子想法
            </button>
          </div>
          <div className="idea-form">
            <h2>策略想法</h2>
            <label>
              <span>标题</span>
              <input value={strategyTitle} onChange={(event) => setStrategyTitle(event.target.value)} />
            </label>
            <label>
              <span>描述</span>
              <textarea value={strategyText} onChange={(event) => setStrategyText(event.target.value)} />
            </label>
            <button type="button" onClick={handleSaveStrategyIdea}>
              保存策略想法
            </button>
          </div>
        </div>
        {message ? <p className="success-message">{message}</p> : null}
      </section>
      <div className="research-grid">
        <section className="panel detail-panel">
          <h2>因子想法库</h2>
          <div className="mini-table">
            {factorIdeas.length === 0 ? <p className="muted-text">暂无因子想法</p> : null}
            {factorIdeas.map((idea) => (
              <div key={idea.idea_id} className="mini-row">
                <span>{idea.title}</span>
                <strong>{idea.status}</strong>
                <em>{idea.direction}</em>
              </div>
            ))}
          </div>
        </section>
        <section className="panel detail-panel">
          <h2>策略想法库</h2>
          <div className="mini-table">
            {strategyIdeas.length === 0 ? <p className="muted-text">暂无策略想法</p> : null}
            {strategyIdeas.map((idea) => (
              <div key={idea.idea_id} className="mini-row">
                <span>{idea.title}</span>
                <strong>{idea.status}</strong>
                <em>{idea.candidate_template}</em>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
