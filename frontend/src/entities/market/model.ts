export interface MarketMetric {
  trade_date: string;
  benchmark_id: string;
  benchmark_nav: number;
  benchmark_return: number;
  benchmark_drawdown: number;
  ma60: number;
  ma120: number;
  trend_state: string;
}
