import { useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { formatBytes } from "../../entities/backup/format";
import { getLogContent } from "../../entities/log/api";
import { logTypeLabel } from "../../entities/log/format";
import type { RuntimeLogContent } from "../../entities/log/model";
import { PageHeader } from "../../shared/ui/PageHeader";

export function LogsPage() {
  const data = useOutletContext<DashboardData>();
  const [selected, setSelected] = useState<RuntimeLogContent | null>(null);
  const [error, setError] = useState("");

  function openLog(logId: string) {
    setError("");
    getLogContent(logId)
      .then(setSelected)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  }

  return (
    <>
      <PageHeader title="日志" description="统一查看服务日志和每日流水线 run_log，便于排查自动运行失败。" />
      <div className="reports-layout">
        <section className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>类型</th>
                <th>名称</th>
                <th>大小</th>
                <th>路径</th>
              </tr>
            </thead>
            <tbody>
              {data.logs.map((log) => (
                <tr key={log.log_id} className="clickable-row" onClick={() => openLog(log.log_id)}>
                  <td>{logTypeLabel(log.log_type)}</td>
                  <td>{log.name}</td>
                  <td>{formatBytes(log.size_bytes)}</td>
                  <td>{log.path}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {error ? <p className="inline-error">{error}</p> : null}
        </section>
        <section className={`panel report-viewer ${selected ? "" : "empty-viewer"}`}>
          {selected ? (
            <>
              <div className="viewer-header">
                <div>
                  <h2>{selected.name}</h2>
                  <p>{selected.path}</p>
                </div>
                <span>{logTypeLabel(selected.log_type)}</span>
              </div>
              <pre>{selected.content}</pre>
            </>
          ) : (
            <span>选择左侧日志查看内容</span>
          )}
        </section>
      </div>
    </>
  );
}
