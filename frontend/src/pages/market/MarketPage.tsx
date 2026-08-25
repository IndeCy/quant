import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { getMarketStyleOverview } from "../../entities/market/api";
import type { MarketBetaSnapshot, MarketMetric, MarketStyleOverview } from "../../entities/market/model";
import { formatNumber, formatPercent } from "../../shared/lib/formatters";
import { ChartPanel } from "../../shared/ui/ChartPanel";
import { PageHeader } from "../../shared/ui/PageHeader";
import { MarketBetaPanel } from "../dashboard/components/MarketBetaPanel";
import { MarketStyleSection } from "./components/MarketStyleSection";

const BETA_LABELS: Record<MarketBetaSnapshot["beta_state"], string> = {
  BETA_ON: "允许承担风险",
  NEUTRAL: "正常观察",
  BETA_OFF: "降低新开仓意愿",
  CRASH_RISK: "优先风险控制"
};

const BETA_TONES: Record<MarketBetaSnapshot["beta_state"], string> = {
  BETA_ON: "success",
  NEUTRAL: "neutral",
  BETA_OFF: "warning",
  CRASH_RISK: "danger"
};

export function MarketPage() {
  const data = useOutletContext<DashboardContext>();
  const [styleOverview, setStyleOverview] = useState<MarketStyleOverview | null>(null);
  const [styleError, setStyleError] = useState("");
  const latestMarket = data.marketSeries[data.marketSeries.length - 1];
  const latestLimitMarket = [...data.marketSeries].reverse().find((item) => item.limit_data_status === "READY");
  const trendSeries = data.marketSeries.slice(-240);
  const observedSeries = data.marketSeries.filter(hasMarketObservation).slice(-120);
  const marketObservationSeries = observedSeries.length > 0 ? observedSeries : data.marketSeries.slice(-120);
  const recentRows = marketObservationSeries.slice(-20).reverse();
  const trendDates = trendSeries.map((item) => item.trade_date);
  const observationDates = marketObservationSeries.map((item) => item.trade_date);

  useEffect(() => {
    let active = true;
    getMarketStyleOverview(240)
      .then((overview) => {
        if (active) {
          setStyleOverview(overview);
          setStyleError("");
        }
      })
      .catch((reason: unknown) => {
        if (active) setStyleError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      active = false;
    };
  }, [data.marketBeta.trade_date]);

  return (
    <>
      <PageHeader
        title="大盘观测"
        description="先判断市场 Beta 是否适合承担风险，再看策略信号和调仓动作。"
      />
      <section className="metrics market-metrics">
        <MarketMetricCard label="Beta状态" value={BETA_LABELS[data.marketBeta.beta_state]} tone={BETA_TONES[data.marketBeta.beta_state]} />
        <MarketMetricCard label="Beta总分" value={formatNumber(data.marketBeta.beta_score, 1)} helper="顺风>=70，中性45-70" />
        <MarketMetricCard
          label="上涨占比"
          value={latestMarket?.breadth_data_status === "READY" ? formatPercent(upRatio(latestMarket), 1) : "待更新"}
          helper="强>=65%，弱<50%"
        />
        <MarketMetricCard label="成交额热度" value={`${formatNumber(latestMarket?.amount_ratio_20, 2)}x`} helper="放量>=1.15x，缩量<0.85x" />
        <MarketMetricCard
          label="涨停/跌停"
          value={latestLimitMarket ? `${latestLimitMarket.limit_up_count ?? 0}/${latestLimitMarket.limit_down_count ?? 0}` : "待更新"}
          helper={latestLimitMarket ? `数据日期 ${latestLimitMarket.trade_date}` : "尚无有效涨跌停观测"}
        />
      </section>
      {styleOverview?.styles.length ? (
        <MarketStyleSection overview={styleOverview} />
      ) : (
        <section className="panel market-style-empty">
          <h2>大小盘风格</h2>
          <p>{styleError || styleOverview?.message || "正在加载风格指数"}</p>
        </section>
      )}
      <div className="content-grid">
        <section className="column wide">
          <ChartPanel
            title="510300趋势（近240日）"
            dates={trendDates}
            series={[
              { name: "510300净值", data: trendSeries.map((item) => item.benchmark_nav) },
              { name: "MA60", data: trendSeries.map((item) => item.ma60) },
              { name: "MA120", data: trendSeries.map((item) => item.ma120) }
            ]}
            scaleYAxis
          />
          <ChartPanel
            title="市场宽度（有效观测日）"
            dates={observationDates}
            series={[
              {
                name: "上涨占比",
                data: marketObservationSeries.map((item) =>
                  item.breadth_data_status === "READY" ? upRatio(item) : Number.NaN
                ),
                valueType: "percent"
              },
              { name: "MA20宽度", data: marketObservationSeries.map((item) => item.ma20_above_ratio ?? 0), valueType: "percent" },
              { name: "MA60宽度", data: marketObservationSeries.map((item) => item.ma60_above_ratio ?? 0), valueType: "percent" }
            ]}
          />
          <ChartPanel
            title="成交额与情绪（有效观测日）"
            dates={observationDates}
            series={[
              { name: "成交额热度", data: marketObservationSeries.map((item) => item.amount_ratio_20 ?? 0) },
              {
                name: "涨停数",
                data: marketObservationSeries.map((item) =>
                  item.limit_data_status === "READY" ? item.limit_up_count ?? 0 : Number.NaN
                ),
                yAxisIndex: 1,
                valueType: "integer"
              },
              {
                name: "跌停数",
                data: marketObservationSeries.map((item) =>
                  item.limit_data_status === "READY" ? item.limit_down_count ?? 0 : Number.NaN
                ),
                yAxisIndex: 1,
                valueType: "integer"
              }
            ]}
            dualAxis
          />
          <ChartPanel
            title="20日新高新低（有效观测日）"
            dates={observationDates}
            series={[
              { name: "新高数", data: marketObservationSeries.map((item) => item.new_high_20_count ?? 0), valueType: "integer" },
              { name: "新低数", data: marketObservationSeries.map((item) => item.new_low_20_count ?? 0), valueType: "integer" }
            ]}
          />
        </section>
        <aside className="column side">
          <MarketBetaPanel snapshot={data.marketBeta} marketSeries={data.marketSeries} />
          <section className="panel">
            <div className="panel-head">
              <h2>操作含义</h2>
              <span className={`status ${BETA_TONES[data.marketBeta.beta_state]}`}>{data.marketBeta.risk_level}</span>
            </div>
            <dl>
              <div>
                <dt>BETA_ON</dt>
                <dd>允许按策略正常承担风险</dd>
              </div>
              <div>
                <dt>NEUTRAL</dt>
                <dd>不主动加风险，按策略观察</dd>
              </div>
              <div>
                <dt>BETA_OFF</dt>
                <dd>降低新开仓意愿</dd>
              </div>
              <div>
                <dt>CRASH_RISK</dt>
                <dd>优先风控和仓位确认</dd>
              </div>
            </dl>
          </section>
        </aside>
      </div>
      <section className="panel table-panel">
        <div className="panel-head">
          <h2>最近状态</h2>
          <span className="status neutral">近20个交易日</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>上涨占比</th>
              <th>MA20宽度</th>
              <th>成交额热度</th>
              <th>涨停/跌停</th>
              <th>新高/新低</th>
              <th>510300涨跌</th>
            </tr>
          </thead>
          <tbody>
            {recentRows.map((item) => (
              <tr key={item.trade_date}>
                <td>{item.trade_date}</td>
                <td>{item.breadth_data_status === "READY" ? formatPercent(upRatio(item), 1) : "待更新"}</td>
                <td>{formatPercent(item.ma20_above_ratio, 1)}</td>
                <td>{formatNumber(item.amount_ratio_20, 2)}x</td>
                <td>
                  {item.limit_data_status === "READY"
                    ? `${item.limit_up_count ?? 0}/${item.limit_down_count ?? 0}`
                    : "待更新"}
                </td>
                <td>{item.new_high_20_count ?? 0}/{item.new_low_20_count ?? 0}</td>
                <td>{formatPercent(item.benchmark_return, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function MarketMetricCard({ label, value, helper, tone = "neutral" }: { label: string; value: string; helper?: string; tone?: string }) {
  return (
    <div className="metric market-metric-card">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
      <small>{helper ?? "当前读数"}</small>
    </div>
  );
}

function upRatio(item: MarketMetric | undefined): number {
  if (!item) return 0;
  const up = item.breadth_up_count ?? 0;
  const down = item.breadth_down_count ?? 0;
  const flat = item.breadth_flat_count ?? 0;
  const total = up + down + flat;
  return total > 0 ? up / total : 0;
}

function hasMarketObservation(item: MarketMetric): boolean {
  return (
    item.breadth_data_status === "READY" ||
    item.limit_data_status === "READY" ||
    (item.market_amount ?? 0) > 0 ||
    (item.breadth_up_count ?? 0) + (item.breadth_down_count ?? 0) + (item.breadth_flat_count ?? 0) > 0 ||
    (item.limit_up_count ?? 0) + (item.limit_down_count ?? 0) > 0 ||
    (item.ma20_above_ratio ?? 0) > 0
  );
}
