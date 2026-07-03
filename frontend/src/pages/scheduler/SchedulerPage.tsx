import { useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { recordOperationsAcknowledgement } from "../../entities/operations/ackApi";
import { ackStatusTone } from "../../entities/operations/ackStatus";
import { decisionTitle, decisionTone } from "../../entities/operations/decisionStatus";
import { observationStatusTone } from "../../entities/operations/status";
import { reviewStatusTitle, reviewStatusTone } from "../../entities/operations/reviewStatus";
import { schedulerNextRunLabel, schedulerStateLabel } from "../../entities/scheduler/status";
import { formatCommand } from "../../entities/service/format";
import { PageHeader } from "../../shared/ui/PageHeader";

export function SchedulerPage() {
  const data = useOutletContext<DashboardContext>();
  const scheduler = data.schedulerStatus;
  const decision = data.operationsDecision;
  const observation = data.operationsObservation;
  const review = data.operationsReview;
  const [ackMessage, setAckMessage] = useState("");
  const observationSections = [
    ["日报产物", observation.run_artifacts],
    ["调度证据", observation.scheduler],
    ["报告产物", observation.held_reports]
  ] as const;

  async function handleAcknowledge(action: typeof decision.actions[number]) {
    await recordOperationsAcknowledgement({
      trade_date: decision.latest_activity_date || decision.latest_run_date,
      source: action.source,
      category: action.category,
      name: action.name,
      severity: action.severity,
      decision: decision.decision,
      message: action.message,
      resolution: action.suggested_action,
      operator: "local_user"
    });
    setAckMessage(`${action.name} 已记录人工确认`);
    await data.refreshData();
  }

  return (
    <>
      <PageHeader title="调度" description="查看本地 APScheduler 每日任务、执行命令和下一次运行时间。" />
      <section className="panel detail-panel">
        <div className="detail-heading">
          <div>
            <h2>今日操作判断</h2>
            <p>聚合就绪度和运行观察证据，只回答是否需要人工介入。</p>
          </div>
          <span className={`status ${decisionTone(decision.severity)}`}>{decisionTitle(decision.decision)}</span>
        </div>
        <div className="config-grid">
          <div>
            <span>严重级别</span>
            <strong>{decision.severity}</strong>
          </div>
          <div>
            <span>人工处理</span>
            <strong>{decision.manual_intervention_required ? "需要" : "不需要"}</strong>
          </div>
          <div>
            <span>最新完整日报</span>
            <strong>{decision.latest_run_date || "暂无"}</strong>
          </div>
          <div>
            <span>下一步</span>
            <strong>{decision.next_action}</strong>
          </div>
        </div>
        {decision.actions.length > 0 ? (
          <div className="decision-action-list">
            {decision.actions.map((action) => (
              <div className="decision-action-row" key={`${action.source}-${action.category}-${action.name}`}>
                <span>
                  <strong>{action.name}</strong>
                  <small>{action.source} / {action.category}</small>
                </span>
                <em className={`status ${decisionTone(action.severity)}`}>{action.severity}</em>
                <p>{action.message}</p>
                <button type="button" onClick={() => handleAcknowledge(action)}>
                  记录已确认
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted-text">当前没有阻断项或告警项，按计划继续观察。</p>
        )}
        {ackMessage ? <p className="success-message">{ackMessage}</p> : null}
      </section>
      <section className="panel detail-panel">
        <div className="detail-heading">
          <div>
            <h2>闭环复盘</h2>
            <p>把当前告警、人工确认和处置记录串起来，观察运维闭环是否完成。</p>
          </div>
          <span className={`status ${reviewStatusTone(review.closure_status)}`}>
            {reviewStatusTitle(review.closure_status)}
          </span>
        </div>
        <div className="config-grid">
          <div>
            <span>当前告警</span>
            <strong>{review.current_action_count}</strong>
          </div>
          <div>
            <span>已确认</span>
            <strong>{review.acknowledged_action_count}</strong>
          </div>
          <div>
            <span>待跟进</span>
            <strong>{review.unacknowledged_action_count}</strong>
          </div>
          <div>
            <span>最近确认</span>
            <strong>{review.latest_ack_at || "暂无"}</strong>
          </div>
        </div>
        {review.unacknowledged_actions.length > 0 ? (
          <div className="review-action-list">
            {review.unacknowledged_actions.slice(0, 5).map((action) => (
              <div className="review-action-row" key={`${action.source}-${action.category}-${action.name}`}>
                <span>
                  <strong>{action.name}</strong>
                  <small>{action.source} / {action.category}</small>
                </span>
                <em className={`status ${decisionTone(action.severity)}`}>{action.severity}</em>
                <p>{action.message}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted-text">当前没有待跟进告警。</p>
        )}
      </section>
      <section className="panel detail-panel">
        <div className="detail-heading">
          <div>
            <h2>人工确认记录</h2>
            <p>记录已经看过的告警、处理动作和处置结果，用于后续复盘。</p>
          </div>
          <span className="status neutral">{data.operationsAcknowledgements.length} 条</span>
        </div>
        {data.operationsAcknowledgements.length === 0 ? (
          <p className="muted-text">暂无人工确认记录</p>
        ) : (
          <div className="ack-list">
            {data.operationsAcknowledgements.map((item) => (
              <div className="ack-row" key={item.ack_id}>
                <span>
                  <strong>{item.name}</strong>
                  <small>{item.trade_date} / {item.source} / {item.category}</small>
                </span>
                <em className={`status ${ackStatusTone(item.status)}`}>{item.status}</em>
                <p>{item.message}</p>
                <small>{item.resolution || "-"}</small>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="panel detail-panel">
        <div className="detail-heading">
          <div>
            <h2>每日任务总览</h2>
            <p>数据更新先执行，策略批处理错后执行；策略批处理内部会运行所有 enabled 策略实例。</p>
          </div>
          <span className={`status ${scheduler.enabled ? "success" : "warning"}`}>
            {schedulerStateLabel(scheduler.enabled, scheduler.job_store_exists)}
          </span>
        </div>
        <div className="config-grid">
          <div>
            <span>主任务</span>
            <strong>{scheduler.job_id}</strong>
          </div>
          <div>
            <span>计划</span>
            <strong>{scheduler.schedule}</strong>
          </div>
          <div>
            <span>下次运行</span>
            <strong>{schedulerNextRunLabel(scheduler.next_run_time)}</strong>
          </div>
          <div>
            <span>任务数量</span>
            <strong>{scheduler.jobs.length}</strong>
          </div>
        </div>
        <div className="path-block">
          <span>启动命令</span>
          <code>{scheduler.start_command}</code>
        </div>
        <div className="path-block">
          <span>调度状态库</span>
          <code>{scheduler.job_store_path}</code>
        </div>
        <div className="path-block">
          <span>调度日志</span>
          <code>{scheduler.log_path}</code>
        </div>
      </section>
      <section className="panel detail-panel">
        <div className="detail-heading">
          <div>
            <h2>运行观察</h2>
            <p>最新完整日报和最新运行活动分开统计，盘前检查不会被误判为盘后日报缺失。</p>
          </div>
          <span className={`status ${observation.ready_for_daily_review ? "success" : "warning"}`}>
            {observation.ready_for_daily_review ? "可观察" : "需检查"}
          </span>
        </div>
        <div className="config-grid">
          <div>
            <span>最新完整日报</span>
            <strong>{observation.latest_run_date || "暂无"}</strong>
          </div>
          <div>
            <span>最新活动</span>
            <strong>{observation.latest_activity_date || "暂无"}</strong>
          </div>
          <div>
            <span>活动类型</span>
            <strong>{observation.latest_activity_type || "unknown"}</strong>
          </div>
          <div>
            <span>Bark</span>
            <strong>{observation.notification.details}</strong>
          </div>
        </div>
        <div className="observation-summary">
          <span className="status success">PASS {observation.summary.pass}</span>
          <span className="status warning">WARN {observation.summary.warn}</span>
          <span className="status danger">FAIL {observation.summary.fail}</span>
        </div>
        <div className="observation-grid">
          {observationSections.map(([title, items]) => (
            <div className="observation-block" key={title}>
              <h3>{title}</h3>
              {Object.entries(items).map(([name, status]) => (
                <div className="observation-row" key={name}>
                  <span>{name}</span>
                  <em className={`status ${observationStatusTone(status)}`}>{status}</em>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
      <section className="panel table-panel">
        <h2>定时任务</h2>
        <table>
          <thead>
            <tr>
              <th>任务ID</th>
              <th>计划</th>
              <th>下次运行</th>
              <th>命令</th>
            </tr>
          </thead>
          <tbody>
            {scheduler.jobs.map((job) => (
              <tr key={job.job_id}>
                <td>{job.job_id}</td>
                <td>{job.schedule}</td>
                <td>{schedulerNextRunLabel(job.next_run_time)}</td>
                <td>
                  <code>{formatCommand(job.command)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {scheduler.jobs.length === 0 ? <p className="muted-text">暂无已登记定时任务</p> : null}
      </section>
    </>
  );
}
