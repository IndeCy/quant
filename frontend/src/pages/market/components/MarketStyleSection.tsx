import type { MarketStyleOverview } from "../../../entities/market/model";
import { relativeStyleDisplay } from "../../../entities/market/styleDisplay";
import { formatPercent } from "../../../shared/lib/formatters";
import { MarketStyleKlinePanel } from "./MarketStyleKlinePanel";

interface MarketStyleSectionProps {
  overview: MarketStyleOverview;
}

export function MarketStyleSection({ overview }: MarketStyleSectionProps) {
  const relative = relativeStyleDisplay(overview.relative_strength.state);
  const micro = overview.styles.find((item) => item.style_id === "micro_cap");
  const large = overview.styles.find((item) => item.style_id === "large_cap");

  return (
    <section className="market-style-section">
      <div className="panel market-style-summary-panel">
        <div className="panel-head">
          <div>
            <h2>大小盘风格</h2>
            <p>数据日期 {overview.as_of || "-"} · 指数原始点位</p>
          </div>
          <span className={`status ${relative.tone}`}>{relative.label}</span>
        </div>
        <div className="market-style-summary-grid">
          <div><span>微盘20日</span><strong>{formatPercent(micro?.summary.return_20, 2)}</strong></div>
          <div><span>大盘20日</span><strong>{formatPercent(large?.summary.return_20, 2)}</strong></div>
          <div><span>20日相对收益</span><strong>{formatPercent(overview.relative_strength.spread_20, 2)}</strong></div>
          <div><span>占优参考</span><strong>±{formatPercent(overview.relative_strength.reference_threshold, 0)}</strong></div>
        </div>
      </div>
      <div className="market-style-chart-grid">
        {overview.styles.map((series) => <MarketStyleKlinePanel key={series.style_id} series={series} />)}
      </div>
    </section>
  );
}
