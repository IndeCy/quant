import { listFactors } from "../entities/factor/api";
import { getMarketSeries } from "../entities/market/api";
import { listReports } from "../entities/report/api";
import { listRuns } from "../entities/run/api";
import { getStrategy, getStrategySeries, listStrategies } from "../entities/strategy/api";

export async function loadDashboardData() {
  const strategyId = "quality_overlay";
  const [strategies, strategy, factors, reports, runs, strategySeries, marketSeries] = await Promise.all([
    listStrategies(),
    getStrategy(strategyId),
    listFactors(),
    listReports(strategyId),
    listRuns(strategyId),
    getStrategySeries(strategyId),
    getMarketSeries("510300")
  ]);
  return { strategies, strategy, factors, reports, runs, strategySeries, marketSeries };
}
