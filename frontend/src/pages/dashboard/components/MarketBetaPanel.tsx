import type { MarketBetaSnapshot, MarketMetric } from "../../../entities/market/model";

interface MarketBetaPanelProps {
  snapshot: MarketBetaSnapshot;
  marketSeries: MarketMetric[];
}

const LABELS: Record<MarketBetaSnapshot["beta_state"], string> = {
  BETA_ON: "Beta顺风",
  NEUTRAL: "Beta中性",
  BETA_OFF: "Beta逆风",
  CRASH_RISK: "极端风险"
};

const CLASS_NAMES: Record<MarketBetaSnapshot["beta_state"], string> = {
  BETA_ON: "success",
  NEUTRAL: "neutral",
  BETA_OFF: "warning",
  CRASH_RISK: "danger"
};

interface ReferenceReading {
  label: string;
  className: "success" | "neutral" | "warning" | "danger";
  hint: string;
}

function formatPercent(value: number | undefined, digits = 1) {
  return `${((value ?? 0) * 100).toFixed(digits)}%`;
}

function formatAmountYi(value: number | undefined) {
  return `${((value ?? 0) / 100000).toFixed(0)}亿`;
}

function classifyUpRatio(value: number): ReferenceReading {
  if (value >= 0.65) return { label: "强", className: "success", hint: "强: >=65% / 中: 50%-65% / 弱: <50%" };
  if (value >= 0.5) return { label: "中", className: "neutral", hint: "强: >=65% / 中: 50%-65% / 弱: <50%" };
  if (value >= 0.35) return { label: "弱", className: "warning", hint: "强: >=65% / 中: 50%-65% / 弱: <50%" };
  return { label: "差", className: "danger", hint: "强: >=65% / 中: 50%-65% / 差: <35%" };
}

function classifyMaWidth(value: number | undefined): ReferenceReading {
  const ratio = value ?? 0;
  if (ratio >= 0.6) return { label: "扩散", className: "success", hint: "扩散: >=60% / 中性: 40%-60% / 收缩: <40%" };
  if (ratio >= 0.4) return { label: "中性", className: "neutral", hint: "扩散: >=60% / 中性: 40%-60% / 收缩: <40%" };
  if (ratio >= 0.25) return { label: "收缩", className: "warning", hint: "扩散: >=60% / 中性: 40%-60% / 冰点: <25%" };
  return { label: "冰点", className: "danger", hint: "扩散: >=60% / 中性: 40%-60% / 冰点: <25%" };
}

function classifyAmountHeat(value: number | undefined): ReferenceReading {
  const ratio = value ?? 0;
  if (ratio >= 1.15) return { label: "放量", className: "success", hint: "放量: >=1.15x / 正常: 0.85-1.15x / 缩量: <0.85x" };
  if (ratio >= 0.85) return { label: "正常", className: "neutral", hint: "放量: >=1.15x / 正常: 0.85-1.15x / 缩量: <0.85x" };
  return { label: "缩量", className: "warning", hint: "放量: >=1.15x / 正常: 0.85-1.15x / 缩量: <0.85x" };
}

function classifyHighLow(high: number | undefined, low: number | undefined): ReferenceReading {
  const highCount = high ?? 0;
  const lowCount = low ?? 0;
  if (highCount >= lowCount * 2 && highCount >= 50) return { label: "强势", className: "success", hint: "强势: 新高显著多于新低 / 风险: 新低多于新高" };
  if (lowCount > highCount) return { label: "风险", className: "warning", hint: "强势: 新高显著多于新低 / 风险: 新低多于新高" };
  return { label: "均衡", className: "neutral", hint: "强势: 新高显著多于新低 / 风险: 新低多于新高" };
}

export function MarketBetaPanel({ snapshot, marketSeries }: MarketBetaPanelProps) {
  const latestMarket = marketSeries[marketSeries.length - 1];
  const up = latestMarket?.breadth_up_count ?? 0;
  const down = latestMarket?.breadth_down_count ?? 0;
  const flat = latestMarket?.breadth_flat_count ?? 0;
  const total = up + down + flat;
  const upRatio = total > 0 ? up / total : 0;
  const upReference = classifyUpRatio(upRatio);
  const maReference = classifyMaWidth(latestMarket?.ma20_above_ratio);
  const amountReference = classifyAmountHeat(latestMarket?.amount_ratio_20);
  const highLowReference = classifyHighLow(latestMarket?.new_high_20_count, latestMarket?.new_low_20_count);
  const scores = [
    ["趋势", snapshot.trend_score],
    ["宽度", snapshot.breadth_score],
    ["情绪", snapshot.sentiment_score],
    ["流动性", snapshot.liquidity_score],
    ["资金", snapshot.funding_score],
    ["估值", snapshot.valuation_score]
  ];
  return (
    <section className="panel beta-panel">
      <div className="panel-head">
        <h2>Beta观测</h2>
        <span className={`status ${CLASS_NAMES[snapshot.beta_state]}`}>{LABELS[snapshot.beta_state]}</span>
      </div>
      <div className="beta-score">
        <strong>{snapshot.beta_score.toFixed(1)}</strong>
        <span>{`${snapshot.trade_date || "未生成"} · 顺风>=70 / 中性45-70 / 逆风25-45 / 风险<25`}</span>
      </div>
      <div className="beta-score-grid">
        {scores.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{Number(value).toFixed(1)}</strong>
          </div>
        ))}
      </div>
      <div className="beta-reading-grid">
        <div>
          <span>上涨占比</span>
          <strong>{formatPercent(upRatio)} <em className={`reference-tag ${upReference.className}`}>{upReference.label}</em></strong>
          <small>{up}涨 / {down}跌 / {flat}平</small>
          <small>{upReference.hint}</small>
        </div>
        <div>
          <span>MA20宽度</span>
          <strong>{formatPercent(latestMarket?.ma20_above_ratio)} <em className={`reference-tag ${maReference.className}`}>{maReference.label}</em></strong>
          <small>站上20日均线股票占比</small>
          <small>{maReference.hint}</small>
        </div>
        <div>
          <span>成交额热度</span>
          <strong>{Number(latestMarket?.amount_ratio_20 ?? 0).toFixed(2)}x <em className={`reference-tag ${amountReference.className}`}>{amountReference.label}</em></strong>
          <small>{formatAmountYi(latestMarket?.market_amount)}</small>
          <small>{amountReference.hint}</small>
        </div>
        <div>
          <span>新高/新低</span>
          <strong>{latestMarket?.new_high_20_count ?? 0}/{latestMarket?.new_low_20_count ?? 0} <em className={`reference-tag ${highLowReference.className}`}>{highLowReference.label}</em></strong>
          <small>20日窗口</small>
          <small>{highLowReference.hint}</small>
        </div>
      </div>
      <ul className="reason-list">
        {snapshot.reasons.slice(0, 6).map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </section>
  );
}
