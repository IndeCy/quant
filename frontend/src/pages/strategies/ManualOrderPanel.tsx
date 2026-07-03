import { useState } from "react";

import { confirmManualOrderBatch, createManualOrdersFromAccount, fillManualOrder, rejectManualOrder } from "../../entities/manualOrder/api";
import type { ManualOrderBatch } from "../../entities/manualOrder/model";
import { manualOrderStatusTone, orderSideLabel } from "../../entities/manualOrder/status";
import { formatNumber } from "../../shared/lib/formatters";

interface ManualOrderPanelProps {
  batch: ManualOrderBatch | null;
  message: string;
  strategyId: string | null;
  onBatchChange: (batch: ManualOrderBatch) => void;
  onMessage: (message: string) => void;
  onRefresh: () => void;
}

export function ManualOrderPanel({ batch, message, strategyId, onBatchChange, onMessage, onRefresh }: ManualOrderPanelProps) {
  const [fillPriceByOrder, setFillPriceByOrder] = useState<Record<string, string>>({});

  async function handleCreate() {
    if (!strategyId) {
      return;
    }
    const next = await createManualOrdersFromAccount(strategyId);
    onBatchChange(next);
    onMessage("已从账户快照生成手工调仓单");
  }

  async function handleConfirm() {
    if (!batch) {
      return;
    }
    const next = await confirmManualOrderBatch(batch.batch_id);
    onBatchChange(next);
    onMessage("手工调仓单已确认，等待人工成交回填");
  }

  async function handleFill(orderId: string, suggestedQuantity: number) {
    const filledPrice = Number(fillPriceByOrder[orderId] || 0);
    await fillManualOrder(orderId, suggestedQuantity, filledPrice);
    onMessage("成交已回填");
    onRefresh();
  }

  async function handleReject(orderId: string) {
    await rejectManualOrder(orderId, "manual_reject");
    onMessage("已记录未成交/拒绝");
    onRefresh();
  }

  return (
    <section className="panel draft-editor">
      <div className="detail-heading">
        <div>
          <h2>手工调仓单</h2>
          <p>从账户漂移生成本地手工订单，确认后再回填人工成交结果。不接券商，不自动下单。</p>
        </div>
        <span className={`status ${manualOrderStatusTone(batch?.status ?? "NONE")}`}>{batch?.status ?? "无批次"}</span>
      </div>
      {message ? <p className="success-message">{message}</p> : null}
      {!batch ? (
        <button type="button" className="primary-action" disabled={!strategyId} onClick={handleCreate}>
          生成手工调仓单
        </button>
      ) : (
        <>
          <div className="config-grid">
            <div>
              <span>交易日</span>
              <strong>{batch.trade_date}</strong>
            </div>
            <div>
              <span>买入金额</span>
              <strong>{formatNumber(batch.total_buy_amount, 2)}</strong>
            </div>
            <div>
              <span>卖出金额</span>
              <strong>{formatNumber(batch.total_sell_amount, 2)}</strong>
            </div>
            <div>
              <span>订单数</span>
              <strong>{batch.orders.length}</strong>
            </div>
          </div>
          {batch.status === "DRAFT" ? (
            <button type="button" className="primary-action" onClick={handleConfirm}>
              确认调仓单
            </button>
          ) : null}
          <div className="manual-order-list">
            {batch.orders.map((order) => (
              <div key={order.order_id} className="manual-order-row">
                <span>
                  {order.symbol}
                  <small>{orderSideLabel(order.side)} / {order.status}</small>
                </span>
                <strong>{formatNumber(order.trade_amount, 2)}</strong>
                <em>{order.suggested_quantity} 股</em>
                {order.status === "CONFIRMED" ? (
                  <div className="manual-order-actions">
                    <input
                      type="number"
                      placeholder="成交价"
                      value={fillPriceByOrder[order.order_id] ?? ""}
                      onChange={(event) => setFillPriceByOrder((items) => ({ ...items, [order.order_id]: event.target.value }))}
                    />
                    <button type="button" onClick={() => handleFill(order.order_id, order.suggested_quantity)}>
                      回填
                    </button>
                    <button type="button" onClick={() => handleReject(order.order_id)}>
                      未成
                    </button>
                  </div>
                ) : (
                  <small>{order.reject_reason || (order.filled_price ? `成交价 ${formatNumber(order.filled_price, 2)}` : "-")}</small>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
