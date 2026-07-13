export interface AccountPosition {
  symbol: string;
  target_weight: number;
  actual_weight: number;
  drift_weight: number;
  target_amount: number;
  actual_amount: number;
  trade_amount: number;
  action: "BUY" | "SELL" | "HOLD" | string;
  quantity: number;
  last_close: number;
}

export interface AccountSnapshot {
  strategy_id: string;
  trade_date: string;
  total_value: number;
  cash: number;
  cash_weight: number;
  position_value: number;
  target_position_weight: number;
  max_abs_drift: number;
  positions: AccountPosition[];
}
