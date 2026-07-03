import { maxDriftLabel } from "../../entities/account/drift";
import type { AccountPosition, AccountSnapshot } from "../../entities/account/model";
import { formatNumber, formatPercent } from "../../shared/lib/formatters";

interface StrategyAccountSnapshotPanelProps {
  accountMessage: string;
  accountPositions: AccountPosition[];
  accountSnapshot: AccountSnapshot | null;
}

export function StrategyAccountSnapshotPanel({
  accountMessage,
  accountPositions,
  accountSnapshot
}: StrategyAccountSnapshotPanelProps) {
  return (
    <section className="panel draft-editor">
      <div className="detail-heading">
        <div>
          <h2>账户快照</h2>
          <p>展示目标仓位、实际仓位和漂移，帮助判断每日流水线是否需要人工调仓确认。</p>
        </div>
        <span className="status neutral">{maxDriftLabel(accountSnapshot)}</span>
      </div>
      {accountMessage ? <p className="muted-text">{accountMessage}</p> : null}
      {accountSnapshot ? (
        <>
          <div className="config-grid">
            <div>
              <span>交易日</span>
              <strong>{accountSnapshot.trade_date}</strong>
            </div>
            <div>
              <span>总资产</span>
              <strong>{formatNumber(accountSnapshot.total_value, 2)}</strong>
            </div>
            <div>
              <span>现金比例</span>
              <strong>{formatPercent(accountSnapshot.cash_weight)}</strong>
            </div>
            <div>
              <span>目标仓位</span>
              <strong>{formatPercent(accountSnapshot.target_position_weight)}</strong>
            </div>
          </div>
          <div className="mini-table">
            {accountPositions.length === 0 ? <p className="muted-text">暂无持仓明细</p> : null}
            {accountPositions.map((position) => (
              <div key={position.symbol} className="account-position-row">
                <span>{position.symbol}</span>
                <strong>{position.action}</strong>
                <em>
                  {formatPercent(position.actual_weight)} / {formatPercent(position.target_weight)}
                </em>
                <small>{formatPercent(position.drift_weight)}</small>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}
