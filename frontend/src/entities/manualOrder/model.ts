export interface ManualOrder {
  order_id: string;
  batch_id: string;
  strategy_id: string;
  trade_date: string;
  symbol: string;
  side: "BUY" | "SELL" | string;
  status: string;
  target_weight: number;
  actual_weight: number;
  drift_weight: number;
  target_amount: number;
  actual_amount: number;
  trade_amount: number;
  suggested_quantity: number;
  suggested_price: number;
  filled_quantity: number;
  filled_price: number;
  reject_reason: string;
}

export interface ManualOrderAuditEvent {
  event_id: string;
  batch_id: string;
  order_id: string;
  event_type: string;
  message: string;
  created_at: string;
}

export interface ManualOrderBatch {
  batch_id: string;
  strategy_id: string;
  trade_date: string;
  status: string;
  source: string;
  total_buy_amount: number;
  total_sell_amount: number;
  orders: ManualOrder[];
  audit_events: ManualOrderAuditEvent[];
}
