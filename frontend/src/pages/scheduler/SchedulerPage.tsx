import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { schedulerNextRunLabel, schedulerStateLabel } from "../../entities/scheduler/status";
import { formatCommand } from "../../entities/service/format";
import { PageHeader } from "../../shared/ui/PageHeader";

export function SchedulerPage() {
  const data = useOutletContext<DashboardContext>();
  const scheduler = data.schedulerStatus;
  return (
    <>
      <PageHeader title="调度" description="查看本地 APScheduler 每日任务、执行命令和下一次运行时间。" />
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
