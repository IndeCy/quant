import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { PageHeader } from "../../shared/ui/PageHeader";

export function FactorsPage() {
  const data = useOutletContext<DashboardData>();
  return (
    <>
      <PageHeader title="因子" description="查看可组合因子库、因子方向、as-of 来源和启用状态。" />
      <section className="panel table-panel">
        <table>
          <thead>
            <tr>
              <th>因子</th>
              <th>分类</th>
              <th>方向</th>
              <th>来源</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {data.factors.map((factor) => (
              <tr key={factor.factor_id}>
                <td>{factor.name}</td>
                <td>{factor.category}</td>
                <td>{factor.direction}</td>
                <td>{factor.source ?? "-"}</td>
                <td>{factor.enabled ? "启用" : "停用"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
