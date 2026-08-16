import type { StrategyInstanceState } from "../../../entities/strategy/model";
import { formatNumber, formatPercent } from "../../../shared/lib/formatters";

interface StrategyHoldingsPanelProps {
  name: string;
  state?: StrategyInstanceState;
}

export function StrategyHoldingsPanel({ name, state }: StrategyHoldingsPanelProps) {
  const holdings = [...(state?.holdings ?? [])].sort((left, right) => right.weight - left.weight);
  return (
    <section className="panel table-panel strategy-holdings-panel">
      <div className="panel-head">
        <div>
          <h2>策略持仓</h2>
          <p>{name} · {state?.trade_date ?? "尚未生成持仓日期"}</p>
        </div>
        <span className="status neutral">{holdings.length}只</span>
      </div>
      {holdings.length === 0 ? (
        <p className="muted-text">暂无策略目标持仓，等待该策略生成一次有效状态。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>代码</th>
              <th>目标权重</th>
              <th>最近收盘价</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((holding) => (
              <tr key={holding.symbol}>
                <td>{holding.symbol}</td>
                <td>{formatPercent(holding.weight)}</td>
                <td>{formatNumber(holding.last_close, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
