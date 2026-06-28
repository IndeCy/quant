export interface ReportIndex {
  report_id: string;
  report_type: string;
  strategy_id: string;
  trade_date: string;
  title: string;
  file_path: string;
  tags: string[];
}

export interface ReportContent extends ReportIndex {
  content: string;
  missing: boolean;
}
