import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { formatPercent } from "../../shared/lib/formatters";
import { PageHeader } from "../../shared/ui/PageHeader";

export function StrategiesPage() {
  const data = useOutletContext<DashboardData>();
  return (
    <>
      <PageHeader title="策略" description="维护策略定义、运行状态、风险层和当前核心指标。" />
      <section className="panel table-panel">
        <table>
          <thead>
            <tr>
              <th>策略</th>
              <th>状态</th>
              <th>类型</th>
              <th>最新日期</th>
              <th>累计收益</th>
              <th>当前回撤</th>
            </tr>
          </thead>
          <tbody>
            {data.strategies.map((strategy) => (
              <tr key={strategy.strategy_id}>
                <td>{strategy.name}</td>
                <td>{strategy.status}</td>
                <td>{strategy.strategy_type}</td>
                <td>{data.strategy.latest_metrics?.trade_date ?? "-"}</td>
                <td>{formatPercent(data.strategy.latest_metrics?.cumulative_return)}</td>
                <td>{formatPercent(data.strategy.latest_metrics?.drawdown)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
