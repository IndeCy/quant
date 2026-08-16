import { useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { saveFactorIdea, saveResearchNote, saveStrategyIdea } from "../../entities/research/api";
import { PageHeader } from "../../shared/ui/PageHeader";
import { ExperimentPanel } from "./ExperimentPanel";
import { HotMoneyLeaderPanel } from "./HotMoneyLeaderPanel";

export function ResearchPage() {
  const data = useOutletContext<DashboardContext>();
  const todos = data.researchTodos;
  const opportunityThemes = data.opportunityThemes;
  const opportunityRankings = data.opportunityRankings;
  const [researchNotes, setResearchNotes] = useState(data.researchNotes);
  const [selectedNoteId, setSelectedNoteId] = useState(data.researchNotes[0]?.note_id ?? "");
  const [factorIdeas, setFactorIdeas] = useState(data.factorIdeas);
  const [strategyIdeas, setStrategyIdeas] = useState(data.strategyIdeas);
  const [noteTitle, setNoteTitle] = useState("中际旭创个股投研");
  const [noteType, setNoteType] = useState("stock");
  const [linkedId, setLinkedId] = useState("300308.SZ");
  const [noteTags, setNoteTags] = useState("AI算力,光模块,高波动,成长股");
  const [noteContent, setNoteContent] = useState("在这里保存最终投研报告，正文支持 Markdown。");
  const [factorTitle, setFactorTitle] = useState("盈利稳定性");
  const [factorText, setFactorText] = useState("过去三年ROA或ROE波动率越低越好，必须按财报披露日as-of。");
  const [strategyTitle, setStrategyTitle] = useState("质量现金流组合");
  const [strategyText, setStrategyText] = useState("使用ROA和OCF_TO_OR组合，月频Top20，进入paper观察。");
  const [message, setMessage] = useState("");
  const researchReports = data.reports.filter((report) => report.tags.includes("research") || report.report_type.includes("research"));
  const selectedNote = researchNotes.find((note) => note.note_id === selectedNoteId) ?? researchNotes[0];

  async function handleSaveResearchNote() {
    const noteId = `research_${Date.now()}`;
    const saved = await saveResearchNote({
      note_id: noteId,
      title: noteTitle,
      note_type: noteType,
      linked_type: noteType === "stock" ? "stock" : noteType,
      linked_id: linkedId,
      summary: noteContent.split("\n").find((line) => line.trim())?.slice(0, 120) ?? "",
      content: noteContent,
      tags: noteTags.split(",").map((item) => item.trim()).filter(Boolean),
      source: "manual_research",
      status: "active"
    });
    setResearchNotes((items) => [saved, ...items]);
    setSelectedNoteId(saved.note_id);
    setMessage("投研报告已保存到历史记录");
    await data.refreshData();
  }

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
      <ExperimentPanel experiments={data.experiments} />
      <HotMoneyLeaderPanel view={data.hotMoneyLeaders} />
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
              <h2>投研记录</h2>
              <p>保存最终报告，不保存冗长过程；可覆盖个股、策略、行业、宏观和复盘。</p>
            </div>
            <span className="status neutral">{researchNotes.length}</span>
          </div>
          <div className="mini-table">
            {researchNotes.length === 0 ? <p className="muted-text">暂无投研记录</p> : null}
            {researchNotes.map((note) => (
              <button
                key={note.note_id}
                className={`mini-row artifact-button ${note.note_id === selectedNote?.note_id ? "selected-row" : ""}`}
                type="button"
                onClick={() => setSelectedNoteId(note.note_id)}
              >
                <span>{note.title}</span>
                <strong>{note.note_type}</strong>
                <em>{note.linked_id || note.status}</em>
              </button>
            ))}
          </div>
        </section>
      </div>
      <section className="panel opportunity-panel">
        <div className="detail-heading">
          <div>
            <h2>强势方向排行</h2>
            <p>每日研究监控生成，按早期起势强度排序；历史案例和已兑现方向会被降权。</p>
          </div>
          <span className="status neutral">{opportunityRankings[0]?.trade_date ?? "未运行"}</span>
        </div>
        <div className="mini-table opportunity-ranking-table">
          {opportunityRankings.length === 0 ? <p className="muted-text">暂无方向排行，等待每日研究监控生成。</p> : null}
          {opportunityRankings.map((item, index) => (
            <div key={`${item.trade_date}:${item.theme_id}`} className="mini-row opportunity-ranking-row">
              <span>
                {index + 1}. {item.name}
                <small>{item.status} / {item.stage}</small>
                <small>{item.summary}</small>
              </span>
              <strong>
                {formatNumber(item.strength_score)}
                <small>强势分</small>
              </strong>
              <em>
                早期 {formatNumber(item.early_signal_score)}
                <br />
                成熟 {formatNumber(item.maturity_score)} / 拥挤 {formatNumber(item.crowding_score)}
              </em>
            </div>
          ))}
        </div>
      </section>
      <section className="panel opportunity-panel">
        <div className="detail-heading">
          <div>
            <h2>产业机会观察池</h2>
            <p>这里维护还没进入策略库的前置研究方向；每日研究监控会更新等级和升级候选，不产生交易信号。</p>
          </div>
          <span className="status neutral">{opportunityThemes.length}</span>
        </div>
        {opportunityThemes.length === 0 ? <p className="muted-text">暂无机会主题</p> : null}
        <div className="opportunity-list">
          {opportunityThemes.map((theme) => {
            const latestRun = theme.monitor_runs[0];
            return (
              <article key={theme.theme_id} className="opportunity-card">
                <div className="opportunity-title">
                  <div>
                    <h3>{theme.name}</h3>
                    <p>{theme.thesis}</p>
                  </div>
                  <span>{theme.stage}</span>
                </div>
                <div className="config-grid opportunity-metrics">
                  <div>
                    <span>观察状态</span>
                    <strong>{theme.status} / {theme.stage}</strong>
                  </div>
                  <div>
                    <span>周期假设</span>
                    <strong>{theme.horizon_years || "-"} 年</strong>
                  </div>
                  <div>
                    <span>升级候选</span>
                    <strong>{boolMetric(latestRun?.metrics, "upgrade_candidate")}</strong>
                  </div>
                  <div>
                    <span>正式入池 / 候选种子</span>
                    <strong>{countMetric(latestRun?.metrics, "eligible_stock_count")} / {countMetric(latestRun?.metrics, "seed_stock_count")}</strong>
                  </div>
                  <div>
                    <span>正式 S/A</span>
                    <strong>{countMetric(latestRun?.metrics, "s_count")} / {countMetric(latestRun?.metrics, "a_count")}</strong>
                  </div>
                </div>
                <div className="opportunity-rules">
                  <p><strong>升级规则</strong>{theme.upgrade_rule || "-"}</p>
                  <p><strong>反证规则</strong>{theme.disconfirm_rule || "-"}</p>
                </div>
                {latestRun ? <p className="opportunity-summary">{latestRun.summary}</p> : null}
                <div className="mini-table opportunity-stocks">
                  {theme.stocks.map((stock) => (
                    <div key={`${theme.theme_id}:${stock.symbol}`} className="mini-row opportunity-stock-row">
                      <span>
                        {stock.name}
                        <small>{stock.symbol}</small>
                        <small>{stock.chain_role || "未标注"} / 信念 {stock.conviction || "-"}</small>
                        <small>{stock.status} / {stock.verification_status || "unverified"}</small>
                        <small>适配 {numberMetric(verificationMetric(stock.evidence), "theme_fit_score")} / {textMetric(verificationMetric(stock.evidence), "theme_fit_grade")}</small>
                        <small>优先级 {numberMetric(priorityMetric(stock.evidence), "score")} / {textMetric(priorityMetric(stock.evidence), "grade")}</small>
                      </span>
                      <strong>
                        {stock.watch_level}
                        <small>早期 {numberMetric(stock.evidence, "early_signal_score")}</small>
                      </strong>
                      <em>
                        成熟 {numberMetric(stock.evidence, "maturity_score")} / 拥挤 {numberMetric(stock.evidence, "crowding_score")}
                        <br />
                        相对强弱 {pctMetric(stock.metrics, "relative_strength_250d")}
                        <br />
                        来源 {stock.source_type || "-"}
                        <br />
                        {firstTextListItem(verificationMetric(stock.evidence), "selection_reasons") || firstTextListItem(verificationMetric(stock.evidence), "evidence_gaps") || "-"}
                        <br />
                        {firstTextListItem(priorityMetric(stock.evidence), "reasons") || firstTextListItem(priorityMetric(stock.evidence), "gaps") || "-"}
                        <br />
                        {boolMetric(stock.evidence, "disconfirm_triggered") === "是" ? "反证触发" : textMetric(stock.evidence, "opportunity_phase")}
                      </em>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      </section>
      <section className="panel report-viewer research-note-viewer">
        {selectedNote ? (
          <>
            <div className="viewer-header">
              <div>
                <h2>{selectedNote.title}</h2>
                <p>{selectedNote.tags.join(" / ") || "未打标签"}</p>
              </div>
              <span>{selectedNote.linked_id || selectedNote.note_type}</span>
            </div>
            <pre>{selectedNote.content}</pre>
          </>
        ) : (
          <div className="empty-viewer">
            <p>暂无投研报告</p>
          </div>
        )}
      </section>
      <section className="panel draft-editor">
        <div className="detail-heading">
          <div>
            <h2>保存投研报告</h2>
            <p>用于沉淀个股研究、策略研究、行业梳理和复盘结论；不会触发策略运行。</p>
          </div>
          <span className="status neutral">Markdown</span>
        </div>
        <div className="research-note-form">
          <label>
            <span>标题</span>
            <input value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} />
          </label>
          <label>
            <span>类型</span>
            <select value={noteType} onChange={(event) => setNoteType(event.target.value)}>
              <option value="stock">个股</option>
              <option value="strategy">策略</option>
              <option value="industry">行业</option>
              <option value="macro">宏观</option>
              <option value="idea">想法</option>
              <option value="review">复盘</option>
            </select>
          </label>
          <label>
            <span>关联对象</span>
            <input value={linkedId} onChange={(event) => setLinkedId(event.target.value)} />
          </label>
          <label>
            <span>标签</span>
            <input value={noteTags} onChange={(event) => setNoteTags(event.target.value)} />
          </label>
        </div>
        <label className="research-note-content">
          <span>正文</span>
          <textarea value={noteContent} onChange={(event) => setNoteContent(event.target.value)} />
        </label>
        <button className="primary-action" type="button" onClick={handleSaveResearchNote}>
          保存投研报告
        </button>
      </section>
      <div className="research-grid">
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

function pctMetric(metrics: Record<string, unknown> | undefined, key: string): string {
  const value = metrics?.[key];
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "-";
}

function countMetric(metrics: Record<string, unknown> | undefined, key: string): string {
  const value = metrics?.[key];
  return typeof value === "number" ? String(value) : "-";
}

function boolMetric(metrics: Record<string, unknown> | undefined, key: string): string {
  return metrics?.[key] === true ? "是" : "否";
}

function numberMetric(metrics: Record<string, unknown> | undefined, key: string): string {
  const value = metrics?.[key];
  return typeof value === "number" ? formatNumber(value) : "-";
}

function textMetric(metrics: Record<string, unknown> | undefined, key: string): string {
  const value = metrics?.[key];
  return typeof value === "string" && value.length > 0 ? value : "-";
}

function verificationMetric(evidence: Record<string, unknown> | undefined): Record<string, unknown> | undefined {
  const value = evidence?.verification;
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : undefined;
}

function priorityMetric(evidence: Record<string, unknown> | undefined): Record<string, unknown> | undefined {
  const value = evidence?.priority;
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : undefined;
}

function firstTextListItem(metrics: Record<string, unknown> | undefined, key: string): string {
  const value = metrics?.[key];
  return Array.isArray(value) && typeof value[0] === "string" ? value[0] : "";
}

function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toFixed(0) : "-";
}
