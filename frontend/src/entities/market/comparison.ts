import type { MarketIndexComparison } from "./model";

export interface MarketIndexComparisonLine {
  name: string;
  data: number[];
}

/**
 * 将指数净值对齐到策略图日期，并在当前可见窗口的首个有效点重新归一为 1。
 */
export function buildMarketIndexComparisonLines(
  comparison: MarketIndexComparison,
  dates: string[]
): MarketIndexComparisonLine[] {
  return comparison.indices
    .map((index) => {
      const navByDate = new Map(index.points.map((point) => [point.trade_date, point.nav]));
      const values = dates.map((date) => navByDate.get(date) ?? Number.NaN);
      const base = values.find((value) => Number.isFinite(value) && value > 0);
      return {
        name: index.name,
        data: base === undefined ? values : values.map((value) => (Number.isFinite(value) ? value / base : Number.NaN))
      };
    })
    .filter((line) => line.data.some((value) => Number.isFinite(value)));
}
