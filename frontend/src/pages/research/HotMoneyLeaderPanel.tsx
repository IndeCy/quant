import type { HotMoneyLeaderView } from "../../entities/research/model";
import { hotMoneyStatusLabel } from "../../entities/research/hotMoney";

export function HotMoneyLeaderPanel({ view }: { view: HotMoneyLeaderView }) {
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
          <strong>{view.latest_trade_date || "-"}</strong>
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
      </div>
      <div className="mini-table opportunity-ranking-table">
        {view.mainlines.length === 0 ? <p className="muted-text">暂无主线识别结果，等待涨跌停缓存生成。</p> : null}
        {view.mainlines.map((item) => (
          <div key={`${item.trade_date}:${item.sector_name}`} className="mini-row opportunity-ranking-row">
            <span>
              {item.rank}. {item.sector_name}
              <small>{item.reason}</small>
            </span>
            <strong>
              {item.sector_score.toFixed(1)}
              <small>强度分</small>
            </strong>
          </div>
        ))}
      </div>
      <div className="mini-table opportunity-stocks">
        {view.leaders.map((item) => (
          <div key={`${item.trade_date}:${item.ts_code}:${item.role}`} className="mini-row opportunity-stock-row">
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
