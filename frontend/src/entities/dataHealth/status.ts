import type { Tone } from "../../shared/lib/formatters";
import type { DataHealth, DataHealthSection } from "./model";

export function healthTone(exists: boolean, dates: Array<string | null | undefined>): Tone {
  if (!exists) {
    return "danger";
  }
  const values = dates.filter(Boolean);
  if (values.length === 0) {
    return "warning";
  }
  return new Set(values).size === 1 ? "success" : "danger";
}

export function dataFreshnessSummary(health: DataHealth): { tone: Tone; label: string; latestDate: string } {
  const sections = [
    health.live_market_increment,
    health.benchmark_increment,
    health.monitoring,
    health.system_state
  ];
  if (sections.some((section) => !section.exists)) {
    return { tone: "danger", label: "存在缺失", latestDate: "-" };
  }
  const dates = sections.flatMap(sectionDates).filter(Boolean) as string[];
  if (dates.length === 0) {
    return { tone: "warning", label: "等待数据", latestDate: "-" };
  }
  const latestDate = dates.sort().at(-1) ?? "-";
  if (new Set(dates).size > 1) {
    return { tone: "danger", label: "日期不一致", latestDate };
  }
  return { tone: "success", label: "全部对齐", latestDate };
}

function sectionDates(section: DataHealthSection): Array<string | null | undefined> {
  return [
    section.latest_daily_date,
    section.latest_adj_factor_date,
    section.latest_fund_date,
    section.latest_fund_adj_date,
    section.latest_index_date,
    section.latest_strategy_date,
    section.latest_market_date,
    section.latest_run_date,
    section.latest_report_date
  ];
}
