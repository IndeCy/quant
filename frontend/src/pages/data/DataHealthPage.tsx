import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { PageHeader } from "../../shared/ui/PageHeader";

export function DataHealthPage() {
  const data = useOutletContext<DashboardData>();
  const latestMarket = data.marketSeries.at(-1);
  return (
    <>
      <PageHeader title="数据" description="跟踪行情、基准和系统状态数据的新鲜度。" />
      <section className="panel compact">
        <dl>
          <div>
            <dt>510300最新日期</dt>
            <dd>{latestMarket?.trade_date ?? "-"}</dd>
          </div>
          <div>
            <dt>策略最新日期</dt>
            <dd>{data.strategy.latest_metrics?.trade_date ?? "-"}</dd>
          </div>
          <div>
            <dt>报告数量</dt>
            <dd>{data.reports.length}</dd>
          </div>
        </dl>
      </section>
    </>
  );
}
