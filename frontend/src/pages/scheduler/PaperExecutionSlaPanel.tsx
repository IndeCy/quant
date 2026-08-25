import type { PaperExecutionSlaView } from "../../entities/scheduler/paperExecutionSla";
import { formatPercent } from "../../shared/lib/formatters";

interface PaperExecutionSlaPanelProps {
  value: PaperExecutionSlaView;
}

export function PaperExecutionSlaPanel({ value }: PaperExecutionSlaPanelProps) {
  const strategies = value.strategies ?? [];
  return (
    <section className="panel detail-panel">
      <div className="detail-heading">
        <div>
          <h2>Paper T+1 执行准入</h2>
          <p>连续交易日执行证据，失败或缺失记录会重新计算连续通过天数。</p>
        </div>
        <span className={`status ${value.progress.gate_status === "PASSED" ? "success" : "warning"}`}>
          {value.progress.gate_status === "PASSED" ? "已达标" : "观察中"}
        </span>
      </div>
      <div className="config-grid">
        <div>
          <span>连续通过</span>
          <strong>{value.progress.current_streak}/{value.progress.required_days} 日</strong>
        </div>
        <div>
          <span>剩余</span>
          <strong>{value.progress.remaining_days} 日</strong>
        </div>
        <div>
          <span>历史通过率</span>
          <strong>{formatPercent(value.progress.pass_rate)}</strong>
        </div>
        <div>
          <span>最新结果</span>
          <strong>{value.progress.latest_trade_date || "暂无"} / {value.progress.latest_status}</strong>
        </div>
      </div>
      <progress
        max={value.progress.required_days}
        value={value.progress.current_streak}
        aria-label="Paper T+1 连续执行准入进度"
      />
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>交易日</th>
              <th>结果</th>
              <th>到期委托</th>
              <th>成交/拒单</th>
              <th>异常</th>
            </tr>
          </thead>
          <tbody>
            {value.history.slice(0, 10).map((item) => (
              <tr key={item.trade_date}>
                <td>{item.trade_date}</td>
                <td>
                  <span className={`status ${item.status === "SUCCESS" ? "success" : "danger"}`}>{item.status}</span>
                </td>
                <td>{item.due_orders}</td>
                <td>{item.filled_orders}/{item.rejected_orders}</td>
                <td>{item.issues.join("；") || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {value.history.length === 0 ? <p className="muted-text">暂无执行 SLA 观察记录</p> : null}
      {strategies.length > 0 ? (
        <>
          <h3>候选策略独立观察</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>策略</th>
                  <th>准入状态</th>
                  <th>连续通过</th>
                  <th>剩余</th>
                  <th>最新证据</th>
                </tr>
              </thead>
              <tbody>
                {strategies.map((item) => (
                  <tr key={item.strategy_id}>
                    <td>{item.strategy_name}</td>
                    <td>
                      <span className={`status ${item.progress.gate_status === "PASSED" ? "success" : "warning"}`}>
                        {item.progress.gate_status === "PASSED" ? "已达标" : "观察中"}
                      </span>
                    </td>
                    <td>{item.progress.current_streak}/{item.progress.required_days} 日</td>
                    <td>{item.progress.remaining_days} 日</td>
                    <td>
                      {item.progress.latest_trade_date
                        ? `${item.progress.latest_trade_date} / ${item.progress.latest_status}`
                        : "尚未开始"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}
