import { useMemo, useState } from "react";

import type { HotMoneyLeaderView } from "../../entities/research/model";
import { formatHotMoneyTradeDate, hotMoneyStatusLabel } from "../../entities/research/hotMoney";
import { formatNumber, formatPercent } from "../../shared/lib/formatters";

export function HotMoneyLeaderPanel({ view }: { view: HotMoneyLeaderView }) {
  const defaultSector = view.mainlines[0]?.sector_name ?? "";
  const [selectedSector, setSelectedSector] = useState(defaultSector);
  const activeSector = view.mainlines.some((item) => item.sector_name === selectedSector) ? selectedSector : defaultSector;
  const selectedStocks = useMemo(
    () => view.sector_limit_ups.filter((item) => item.sector_name === activeSector),
    [activeSector, view.sector_limit_ups]
  );

  return (
    <section className="panel opportunity-panel">
      <div className="detail-heading">
        <div>
          <h2>游资主线与龙头</h2>
          <p>基于涨跌停缓存识别主线板块、唯一龙头和次级龙头；只做研究观察，不触发交易。</p>
        </div>
        <span className={`status ${view.status === "READY" ? "positive" : "neutral"}`}>
          {hotMoneyStatusLabel(view.status)}
        </span>
      </div>
      <div className="config-grid">
        <div>
          <span>最新交易日</span>
          <strong>{formatHotMoneyTradeDate(view.latest_trade_date)}</strong>
        </div>
        <div>
          <span>主线数量</span>
          <strong>{view.mainlines.length}</strong>
        </div>
        <div>
          <span>龙头候选</span>
          <strong>{view.leaders.length}</strong>
        </div>
        <div>
          <span>状态说明</span>
          <strong>{view.message}</strong>
        </div>
        <div>
          <span>数据口径</span>
          <strong>Tushare涨跌停榜缓存，非实时盘口</strong>
        </div>
      </div>
      <div className="mini-table opportunity-ranking-table">
        {view.mainlines.length === 0 ? <p className="muted-text">暂无主线识别结果，等待涨跌停缓存生成。</p> : null}
        {view.mainlines.map((item) => (
          <button
            key={`${item.trade_date}:${item.sector_name}`}
            className={`mini-row opportunity-ranking-row hot-money-sector-row ${item.sector_name === activeSector ? "selected-row" : ""}`}
            type="button"
            onClick={() => setSelectedSector(item.sector_name)}
          >
            <span>
              {item.rank}. {item.sector_name}
              <small>{item.reason}</small>
            </span>
            <strong>
              {item.sector_score.toFixed(1)}
              <small>强度分</small>
            </strong>
            <em>点击查看涨停票</em>
          </button>
        ))}
      </div>
      {activeSector ? (
        <div className="hot-money-detail">
          <div className="detail-heading compact-heading">
            <div>
              <h3>{formatHotMoneyTradeDate(view.latest_trade_date)} {activeSector}涨停明细</h3>
              <p>展示该交易日缓存中的全部涨停样本，不代表今天盘中实时状态。</p>
            </div>
            <span className="status neutral">{selectedStocks.length}</span>
          </div>
          <div className="mini-table opportunity-stocks">
            {selectedStocks.map((item) => (
              <div key={`${item.trade_date}:${item.sector_name}:${item.ts_code}`} className="mini-row hot-money-limit-row">
                <span>
                  {item.name}
                  <small>{item.ts_code} / {item.role}</small>
                  <small>首次 {item.first_time || "-"} / 最后 {item.last_time || "-"}</small>
                </span>
                <strong>
                  {item.limit_streak}
                  <small>连板</small>
                </strong>
                <em>
                  涨幅 {formatPercent(item.pct_chg / 100)}
                  <br />
                  成交额 {formatNumber(item.amount)}
                  <br />
                  占板块 {formatPercent(item.amount_share)}
                  <br />
                  开板 {item.open_times} 次
                </em>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className="mini-table opportunity-stocks">
        {view.leaders.length > 0 ? <p className="muted-text">龙头候选摘要</p> : null}
        {view.leaders.map((item) => (
          <div key={`${item.trade_date}:${item.sector_name}:${item.ts_code}:${item.role}`} className="mini-row opportunity-stock-row">
            <span>
              {item.name}
              <small>{item.ts_code} / {item.sector_name}</small>
              <small>{item.role} / 连板 {item.limit_streak}</small>
            </span>
            <strong>
              {item.leader_score.toFixed(1)}
              <small>龙头分</small>
            </strong>
            <em>{item.reason}</em>
          </div>
        ))}
      </div>
    </section>
  );
}
