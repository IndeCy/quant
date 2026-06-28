import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { PageHeader } from "../../shared/ui/PageHeader";

export function RunsPage() {
  const data = useOutletContext<DashboardData>();
  return (
    <>
      <PageHeader title="运行" description="查看每日流水线运行状态、运行目录和失败信息。" />
      <section className="panel table-panel">
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>策略</th>
              <th>状态</th>
              <th>信息</th>
              <th>目录</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((run) => (
              <tr key={`${run.strategy_id}-${run.trade_date}`}>
                <td>{run.trade_date}</td>
                <td>{run.strategy_id}</td>
                <td>{run.status}</td>
                <td>{run.message || "-"}</td>
                <td>{run.run_dir}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
