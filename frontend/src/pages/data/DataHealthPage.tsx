import { useEffect, useState } from "react";

import { getDataSource, listDataSources, refreshDataCatalog, runDataQualityGate } from "../../entities/dataCatalog/api";
import type { DataQualityGateResult, DataSource, DataSourceDetail } from "../../entities/dataCatalog/model";
import { catalogTone, formatBytes, qualityGateSummary } from "../../entities/dataCatalog/status";
import { getDataHealth } from "../../entities/dataHealth/api";
import type { DataHealth, DataHealthSection } from "../../entities/dataHealth/model";
import { dataFreshnessSummary, healthTone } from "../../entities/dataHealth/status";
import { PageHeader } from "../../shared/ui/PageHeader";

export function DataHealthPage() {
  const [health, setHealth] = useState<DataHealth | null>(null);
  const [sources, setSources] = useState<DataSource[]>([]);
  const [selectedSource, setSelectedSource] = useState<DataSourceDetail | null>(null);
  const [gateResult, setGateResult] = useState<DataQualityGateResult | null>(null);
  const [error, setError] = useState("");
  const [catalogMessage, setCatalogMessage] = useState("");

  useEffect(() => {
    getDataHealth()
      .then(setHealth)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
    listDataSources()
      .then((items) => {
        setSources(items);
        if (items[0]) {
          return getDataSource(items[0].dataset_id);
        }
        return null;
      })
      .then((detail) => {
        if (detail) {
          setSelectedSource(detail);
        }
      })
      .catch((reason: unknown) => setCatalogMessage(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  async function handleRefreshCatalog() {
    setCatalogMessage("");
    const result = await refreshDataCatalog();
    const items = await listDataSources();
    setSources(items);
    setCatalogMessage(`刷新完成：${result.ok_count}/${result.source_count} OK`);
    if (items[0]) {
      setSelectedSource(await getDataSource(items[0].dataset_id));
    }
  }

  async function handleRunQualityGate() {
    setCatalogMessage("");
    const result = await runDataQualityGate();
    setGateResult(result);
  }

  async function handleSelectSource(datasetId: string) {
    setCatalogMessage("");
    setSelectedSource(await getDataSource(datasetId));
  }

  return (
    <>
      <PageHeader title="数据" description="跟踪行情、基准和系统状态数据的新鲜度。" />
      {error ? <section className="panel compact missing-file">{error}</section> : null}
      {!health ? <section className="panel compact">加载中</section> : <HealthGrid health={health} />}
      <DataCatalogPanel
        sources={sources}
        selectedSource={selectedSource}
        gateResult={gateResult}
        message={catalogMessage}
        onRefresh={handleRefreshCatalog}
        onRunGate={handleRunQualityGate}
        onSelectSource={handleSelectSource}
      />
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

function DataCatalogPanel({
  sources,
  selectedSource,
  gateResult,
  message,
  onRefresh,
  onRunGate,
  onSelectSource
}: {
  sources: DataSource[];
  selectedSource: DataSourceDetail | null;
  gateResult: DataQualityGateResult | null;
  message: string;
  onRefresh: () => Promise<void>;
  onRunGate: () => Promise<void>;
  onSelectSource: (datasetId: string) => Promise<void>;
}) {
  const gateSummary = qualityGateSummary(gateResult);
  return (
    <div className="management-layout">
      <section className="panel table-panel">
        <div className="detail-heading">
          <div>
            <h2>Data Catalog</h2>
            <p>统一登记本地 DuckDB / SQLite 数据资产，迁移和排障以这里为准。</p>
          </div>
          <button type="button" className="secondary-button" onClick={onRefresh}>
            刷新目录
          </button>
        </div>
        {message ? <p className="success-message">{message}</p> : null}
        <table>
          <thead>
            <tr>
              <th>数据源</th>
              <th>类型</th>
              <th>状态</th>
              <th>最新日期</th>
              <th>大小</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.dataset_id} className="clickable-row" onClick={() => onSelectSource(source.dataset_id)}>
                <td>{source.dataset_id}</td>
                <td>{source.database_type}</td>
                <td>
                  <span className={`status ${catalogTone(source.status)}`}>{source.status}</span>
                </td>
                <td>{source.latest_date || "-"}</td>
                <td>{formatBytes(source.size_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <aside className="panel detail-panel">
        <div className="detail-heading">
          <div>
            <h2>Quality Gate</h2>
            <p>检查关键行情、复权和基准数据是否满足生产运行要求。</p>
          </div>
          <button type="button" onClick={onRunGate}>
            运行门禁
          </button>
        </div>
        <span className={`status ${gateSummary.tone}`}>{gateSummary.label}</span>
        <div className="mini-table">
          {(gateResult?.checks ?? []).map((check) => (
            <div key={`${check.dataset_id}-${check.table_name}`} className="mini-row">
              <span>{check.dataset_id}.{check.table_name}</span>
              <strong>{check.latest_date || "-"}</strong>
              <em>{check.message}</em>
            </div>
          ))}
        </div>
        <h2>数据源详情</h2>
        {selectedSource ? (
          <>
            <p className="muted-text">{selectedSource.file_path}</p>
            <div className="mini-table">
              {selectedSource.tables.map((table) => (
                <div key={table.table_name} className="mini-row">
                  <span>{table.table_name}</span>
                  <strong>{table.latest_date || "-"}</strong>
                  <em>{table.date_field || "no date"} / {table.row_count} rows</em>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="muted-text">暂无数据源详情</p>
        )}
      </aside>
    </div>
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
