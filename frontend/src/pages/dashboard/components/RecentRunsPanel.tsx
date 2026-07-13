import type { StrategyRun } from "../../../entities/run/model";

export function RecentRunsPanel({ runs }: { runs: StrategyRun[] }) {
  return (
    <section className="panel compact">
      <h2>运行记录</h2>
      {runs.slice(0, 5).map((run) => (
        <div className="list-row" key={`${run.strategy_id}-${run.trade_date}`}>
          <span>{run.trade_date}</span>
          <strong>{run.status}</strong>
        </div>
      ))}
    </section>
  );
}
