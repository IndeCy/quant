import { useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { formatBytes } from "../../entities/backup/format";
import { configureSchedulerJob } from "../../entities/scheduler/api";
import { validateSchedulerConfig } from "../../entities/scheduler/config";
import type { SchedulerStatus } from "../../entities/scheduler/model";
import { schedulerNextRunLabel, schedulerStateLabel } from "../../entities/scheduler/status";
import { formatCommand } from "../../entities/service/format";
import { serviceStatusLabel } from "../../entities/service/status";
import { PageHeader } from "../../shared/ui/PageHeader";

export function SettingsPage() {
  const data = useOutletContext<DashboardData>();
  const [scheduler, setScheduler] = useState<SchedulerStatus>(data.schedulerStatus);
  const [hour, setHour] = useState(16);
  const [minute, setMinute] = useState(30);
  const [skipUpdate, setSkipUpdate] = useState(false);
  const [push, setPush] = useState(false);
  const [schedulerMessage, setSchedulerMessage] = useState("");
  const backup = data.backupManifest;
  const serviceManifest = data.serviceManifest;
  const serviceStatus = data.serviceStatus;
  const schedulerValidation = validateSchedulerConfig(hour, minute);

  async function handleConfigureScheduler() {
    if (!schedulerValidation.valid) {
      setSchedulerMessage(schedulerValidation.message);
      return;
    }
    const updated = await configureSchedulerJob({ hour, minute, skip_update: skipUpdate, push });
    setScheduler(updated);
    setSchedulerMessage("每日任务已登记到本地调度状态库");
  }

  return (
    <>
      <PageHeader title="设置" description="后续维护 QUANT_HOME、通知、调度和备份策略。" />
      <div className="settings-grid">
        <section className="panel detail-panel">
          <div className="detail-heading">
            <div>
              <h2>每日调度器</h2>
              <p>APScheduler 使用 SQLite job store 保存盘后运行任务，适合迁移到常驻 Mac mini 后托管。</p>
            </div>
            <span className={`status ${scheduler.enabled ? "success" : "warning"}`}>
              {schedulerStateLabel(scheduler.enabled, scheduler.job_store_exists)}
            </span>
          </div>
          <div className="config-grid">
            <div>
              <span>任务ID</span>
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
              <span>Job Store</span>
              <strong>{scheduler.job_store_exists ? "存在" : "未创建"}</strong>
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
          <div className="scheduler-form">
            <label>
              <span>小时</span>
              <input type="number" min="0" max="23" value={hour} onChange={(event) => setHour(Number(event.target.value))} />
            </label>
            <label>
              <span>分钟</span>
              <input type="number" min="0" max="59" value={minute} onChange={(event) => setMinute(Number(event.target.value))} />
            </label>
            <label className="checkbox-label">
              <input type="checkbox" checked={skipUpdate} onChange={(event) => setSkipUpdate(event.target.checked)} />
              <span>跳过数据更新</span>
            </label>
            <label className="checkbox-label">
              <input type="checkbox" checked={push} onChange={(event) => setPush(event.target.checked)} />
              <span>运行后推送</span>
            </label>
            <button type="button" onClick={handleConfigureScheduler}>
              登记任务
            </button>
          </div>
          {schedulerMessage ? (
            <p className={schedulerValidation.valid ? "success-message" : "inline-error"}>{schedulerMessage}</p>
          ) : null}
        </section>

        <section className="panel detail-panel">
          <div className="detail-heading">
            <div>
              <h2>迁移边界</h2>
              <p>第一阶段本地访问即可，所有可变数据集中在运行目录，降低后续迁移成本。</p>
            </div>
          </div>
          <div className="path-block">
            <span>运行目录</span>
            <code>{data.strategy.latest_run?.run_dir ? data.strategy.latest_run.run_dir.replace(/\/runs\/.+$/, "") : "-"}</code>
          </div>
          <div className="path-block">
            <span>运行产物</span>
            <code>{data.strategy.latest_run?.run_dir ?? "-"}</code>
          </div>
          <div className="path-block">
            <span>当前状态</span>
            <code>本地只读配置页，写入能力仅限策略草案。</code>
          </div>
        </section>
      </div>
      <section className="panel backup-panel">
        <div className="detail-heading">
          <div>
            <h2>备份清单</h2>
            <p>这些目录构成最低迁移集合，后续迁移机器时优先整体备份和恢复。</p>
          </div>
          <span className="status neutral">{backup.items.length} 项</span>
        </div>
        <div className="path-block">
          <span>备份命令</span>
          <code>{backup.backup_command}</code>
        </div>
        <div className="table-panel">
          <table>
            <thead>
              <tr>
                <th>目录</th>
                <th>状态</th>
                <th>文件数</th>
                <th>大小</th>
                <th>路径</th>
              </tr>
            </thead>
            <tbody>
              {backup.items.map((item) => (
                <tr key={item.name}>
                  <td>{item.name}</td>
                  <td>{item.exists ? "存在" : "缺失"}</td>
                  <td>{item.file_count}</td>
                  <td>{formatBytes(item.size_bytes)}</td>
                  <td>{item.path}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel backup-panel">
        <div className="detail-heading">
          <div>
            <h2>常驻服务模板</h2>
            <p>这里生成 API、前端和调度器的启动命令与 launchd 模板，确认后再安装到 Mac mini。</p>
          </div>
          <span className="status neutral">{serviceManifest.services.length} 项</span>
        </div>
        <div className="service-list">
          {serviceManifest.services.map((service) => (
            <div key={service.name} className="service-block">
              <div className="detail-heading">
                <div>
                  <h2>{service.name}</h2>
                  <p>{service.label}</p>
                </div>
                <span className={`status ${serviceStatus.services.find((item) => item.name === service.name)?.running ? "success" : "warning"}`}>
                  {serviceStatusLabel(Boolean(serviceStatus.services.find((item) => item.name === service.name)?.running))}
                </span>
              </div>
              <div className="path-block">
                <span>巡检</span>
                <code>{serviceStatus.services.find((item) => item.name === service.name)?.check ?? "-"}</code>
              </div>
              <div className="path-block">
                <span>启动命令</span>
                <code>{formatCommand(service.command)}</code>
              </div>
              <div className="path-block">
                <span>工作目录</span>
                <code>{service.cwd}</code>
              </div>
              <div className="path-block">
                <span>launchd 模板</span>
                <code>{service.launchd_plist}</code>
              </div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
