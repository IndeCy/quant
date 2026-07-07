export interface ResearchTodos {
  title: string;
  path: string;
  content: string;
  missing: boolean;
}

export interface FactorIdea {
  idea_id: string;
  title: string;
  raw_description: string;
  source: string;
  hypothesis: string;
  required_data: string[];
  as_of_requirement: string;
  direction: string;
  status: string;
  created_at?: string;
  modified_at?: string;
}

export interface StrategyIdea {
  idea_id: string;
  title: string;
  raw_description: string;
  source: string;
  hypothesis: string;
  candidate_template: string;
  required_factors: string[];
  status: string;
  created_at?: string;
  modified_at?: string;
}

export type ResearchNoteType = "stock" | "strategy" | "industry" | "macro" | "idea" | "review";

export interface ResearchNote {
  note_id: string;
  title: string;
  note_type: ResearchNoteType | string;
  linked_type: string;
  linked_id: string;
  summary: string;
  content: string;
  tags: string[];
  source: string;
  status: string;
  created_at?: string;
  modified_at?: string;
}

export interface OpportunityStock {
  theme_id: string;
  symbol: string;
  name: string;
  status: string;
  watch_level: string;
  chain_role: string;
  conviction: string;
  source_type: string;
  source_detail: string;
  verification_status: string;
  first_observed_date: string;
  thesis: string;
  disconfirm_condition: string;
  evidence: Record<string, unknown>;
  metrics: Record<string, unknown>;
  last_monitor_date: string;
  created_at?: string;
  modified_at?: string;
}

export interface ResearchMonitorRun {
  run_id: string;
  trade_date: string;
  theme_id: string;
  status: string;
  summary: string;
  metrics: Record<string, unknown>;
  created_at?: string;
  modified_at?: string;
}

export interface OpportunityTheme {
  theme_id: string;
  name: string;
  status: string;
  stage: string;
  horizon_years: number;
  thesis_type: string;
  thesis: string;
  upgrade_rule: string;
  disconfirm_rule: string;
  linked_note_id: string;
  tags: string[];
  stocks: OpportunityStock[];
  monitor_runs: ResearchMonitorRun[];
  created_at?: string;
  modified_at?: string;
}

export interface OpportunityRanking {
  trade_date: string;
  theme_id: string;
  name: string;
  status: string;
  stage: string;
  strength_score: number;
  early_signal_score: number;
  maturity_score: number;
  crowding_score: number;
  upgrade_candidate: boolean;
  summary: string;
  metrics: Record<string, unknown>;
  created_at?: string;
  modified_at?: string;
}

export interface HotMoneyMainline {
  trade_date: string;
  sector_name: string;
  sector_score: number;
  rank: number;
  reason: string;
}

export interface HotMoneyLeader {
  trade_date: string;
  sector_name: string;
  ts_code: string;
  name: string;
  role: string;
  leader_score: number;
  limit_streak: number;
  amount_share: number;
  reason: string;
}

export interface HotMoneyLimitUpStock extends HotMoneyLeader {
  close: number;
  pct_chg: number;
  amount: number;
  fd_amount: number;
  first_time: string;
  last_time: string;
  open_times: number;
}

export interface HotMoneyLeaderView {
  status: string;
  message: string;
  cache_path: string;
  latest_trade_date: string;
  mainlines: HotMoneyMainline[];
  leaders: HotMoneyLeader[];
  sector_limit_ups: HotMoneyLimitUpStock[];
}
