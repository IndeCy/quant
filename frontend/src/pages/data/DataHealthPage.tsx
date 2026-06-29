import { useEffect, useState } from "react";

import { getDataHealth } from "../../entities/dataHealth/api";
import type { DataHealth, DataHealthSection } from "../../entities/dataHealth/model";
import { dataFreshnessSummary, healthTone } from "../../entities/dataHealth/status";
import { PageHeader } from "../../shared/ui/PageHeader";

export function DataHealthPage() {
  const [health, setHealth] = useState<DataHealth | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getDataHealth()
      .then(setHealth)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  return (
    <>
      <PageHeader title="数据" description="跟踪行情、基准和系统状态数据的新鲜度。" />
      {error ? <section className="panel compact missing-file">{error}</section> : null}
      {!health ? <section className="panel compact">加载中</section> : <HealthGrid health={health} />}
    </>
  );
}

function HealthGrid({ health }: { health: DataHealth }) {
  const summary = dataFreshnessSummary(health);
  return (
    <>
      <section className="panel compact health-summary">
        <div>
          <span>运行目录</span>
          <strong>{health.runtime_root}</strong>
        </div>
        <div>
          <span>最新日期</span>
          <strong>{summary.latestDate}</strong>
        </div>
        <span className={`status ${summary.tone}`}>{summary.label}</span>
      </section>
      <div className="health-grid">
        <HealthCard
          title="A股增量行情"
          section={health.live_market_increment}
          rows={[
            ["日线", health.live_market_increment.latest_daily_date],
            ["复权因子", health.live_market_increment.latest_adj_factor_date]
          ]}
        />
        <HealthCard
          title="基准增量行情"
          section={health.benchmark_increment}
          rows={[
            ["510300", health.benchmark_increment.latest_fund_date],
            ["ETF复权", health.benchmark_increment.latest_fund_adj_date],
            ["上证指数", health.benchmark_increment.latest_index_date]
          ]}
        />
        <HealthCard
          title="监控指标库"
          section={health.monitoring}
          rows={[
            ["策略指标", health.monitoring.latest_strategy_date],
            ["市场指标", health.monitoring.latest_market_date]
          ]}
        />
        <HealthCard
          title="系统状态库"
          section={health.system_state}
          rows={[
            ["运行记录", health.system_state.latest_run_date],
            ["报告索引", health.system_state.latest_report_date]
          ]}
        />
      </div>
    </>
  );
}

function HealthCard({ title, section, rows }: { title: string; section: DataHealthSection; rows: Array<[string, string | null | undefined]> }) {
  const tone = healthTone(
    section.exists,
    rows.map(([, value]) => value)
  );
  return (
    <section className="panel compact health-card">
      <div className="health-title">
        <h2>{title}</h2>
        <span className={`status ${tone}`}>{section.exists ? tone : "missing"}</span>
      </div>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value ?? "-"}</dd>
          </div>
        ))}
        <div>
          <dt>文件</dt>
          <dd>{section.path}</dd>
        </div>
      </dl>
    </section>
  );
}
