export interface MarketMetric {
  trade_date: string;
  benchmark_id: string;
  benchmark_nav: number;
  benchmark_return: number;
  benchmark_drawdown: number;
  ma60: number;
  ma120: number;
  trend_state: string;
  breadth_up_count?: number;
  breadth_down_count?: number;
  breadth_flat_count?: number;
  limit_up_count?: number;
  limit_down_count?: number;
  equal_weight_return?: number;
  median_return?: number;
  ma20_above_ratio?: number;
  ma60_above_ratio?: number;
  ma120_above_ratio?: number;
  new_high_20_count?: number;
  new_low_20_count?: number;
  market_amount?: number;
  amount_ma20?: number;
  amount_ratio_20?: number;
  low_amount_ratio?: number;
  zero_volume_ratio?: number;
}

export interface MarketBetaSnapshot {
  trade_date: string;
  beta_state: "BETA_ON" | "NEUTRAL" | "BETA_OFF" | "CRASH_RISK";
  beta_score: number;
  trend_score: number;
  breadth_score: number;
  sentiment_score: number;
  liquidity_score: number;
  funding_score: number;
  valuation_score: number;
  risk_level: string;
  reasons: string[];
}

export type MarketStyleTrendState = "UP" | "DOWN" | "REBOUND" | "WEAK" | "INSUFFICIENT";
export type RelativeStyleState = "MICRO_STRONG" | "LARGE_STRONG" | "BALANCED" | "UNKNOWN";

export interface MarketStyleBar {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  pct_chg: number | null;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma60: number | null;
}

export interface MarketStyleSummary {
  trade_date: string;
  close: number;
  return_20: number | null;
  return_60: number | null;
  distance_ma20: number | null;
  distance_ma60: number | null;
  trend_state: MarketStyleTrendState;
}

export interface MarketStyleSeries {
  style_id: "micro_cap" | "large_cap";
  name: string;
  symbol: string;
  proxy_name: string;
  bars: MarketStyleBar[];
  summary: MarketStyleSummary;
}

export interface MarketRelativeStrength {
  state: RelativeStyleState;
  spread_20: number | null;
  reference_threshold: number;
  series: Array<{ trade_date: string; relative_nav: number }>;
}

export interface MarketStyleOverview {
  data_status: "READY" | "PARTIAL" | "MISSING";
  as_of: string;
  adjust_policy: "index_raw";
  message?: string;
  styles: MarketStyleSeries[];
  relative_strength: MarketRelativeStrength;
}
