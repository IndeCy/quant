export interface DataHealthSection {
  path: string;
  exists: boolean;
  latest_daily_date?: string | null;
  latest_adj_factor_date?: string | null;
  latest_fund_date?: string | null;
  latest_fund_adj_date?: string | null;
  latest_index_date?: string | null;
  latest_strategy_date?: string | null;
  latest_market_date?: string | null;
  latest_run_date?: string | null;
  latest_report_date?: string | null;
}

export interface DataHealth {
  runtime_root: string;
  live_market_increment: DataHealthSection;
  benchmark_increment: DataHealthSection;
  monitoring: DataHealthSection;
  system_state: DataHealthSection;
}
