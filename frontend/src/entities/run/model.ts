export interface StrategyRun {
  strategy_id: string;
  trade_date: string;
  status: string;
  run_dir: string;
  message: string;
}

export interface StrategyRunStep {
  strategy_id: string;
  trade_date: string;
  sequence: number;
  step_name: string;
  status: string;
  message: string;
  artifact_path: string;
}

export interface StrategyRunDetail {
  run: StrategyRun;
  steps: StrategyRunStep[];
  artifacts: Array<{
    report_id: string;
    report_type: string;
    strategy_id: string;
    trade_date: string;
    title: string;
    file_path: string;
    tags: string[];
  }>;
}
