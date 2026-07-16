import type { StrategyMetric } from "./model";

export interface PaperWindow {
  dates: string[];
  paperNav: number[];
  theoreticalNav: number[];
  benchmarkNav: number[];
}

function rebase(values: number[]): number[] {
  const base = values[0];
  if (!Number.isFinite(base) || base <= 0) {
    return values.map(() => Number.NaN);
  }
  return values.map((value) => value / base);
}

/**
 * 截取真实存在模拟盘快照的观察窗口，并统一净值起点以便公平比较。
 */
export function buildPaperWindow(rows: StrategyMetric[]): PaperWindow {
  const paperRows = rows
    .filter((row) => typeof row.paper_nav === "number" && Number.isFinite(row.paper_nav) && row.paper_nav > 0)
    .sort((left, right) => left.trade_date.localeCompare(right.trade_date));
  if (paperRows.length === 0) {
    return { dates: [], paperNav: [], theoreticalNav: [], benchmarkNav: [] };
  }
  return {
    dates: paperRows.map((row) => row.trade_date),
    paperNav: rebase(paperRows.map((row) => row.paper_nav as number)),
    theoreticalNav: rebase(paperRows.map((row) => row.nav)),
    benchmarkNav: rebase(paperRows.map((row) => row.benchmark_nav))
  };
}
