import { useEffect, useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { AppLayout } from "./app/layout/AppLayout";
import { loadDeferredDashboardData } from "./app/loadDeferredDashboardData";
import { loadDashboardData } from "./app/loadDashboardData";
import { mergeRuntimeStatus } from "./app/state";
import type { DashboardContext, DashboardData } from "./app/types";
import type { ReadinessReport } from "./entities/readiness/model";
import type { SchedulerStatus } from "./entities/scheduler/model";
import { getStrategy, getStrategySeries } from "./entities/strategy/api";
import { DashboardPage } from "./pages/dashboard/DashboardPage";
import { DataHealthPage } from "./pages/data/DataHealthPage";
import { FactorsPage } from "./pages/factors/FactorsPage";
import { LogsPage } from "./pages/logs/LogsPage";
import { MarketPage } from "./pages/market/MarketPage";
import { ReportsPage } from "./pages/reports/ReportsPage";
import { ResearchPage } from "./pages/research/ResearchPage";
import { RiskPage } from "./pages/risk/RiskPage";
import { RunsPage } from "./pages/runs/RunsPage";
import { SchedulerPage } from "./pages/scheduler/SchedulerPage";
import { SettingsPage } from "./pages/settings/SettingsPage";
import { StrategiesPage } from "./pages/strategies/StrategiesPage";
import "./shared/styles/global.css";
import "./shared/styles/features.css";
import "./shared/styles/operations.css";
import "./shared/styles/researchExperiments.css";
import "./shared/styles/hotMoney.css";
import "./shared/styles/acknowledgement.css";
import "./shared/styles/workbench.css";
import "./shared/styles/environment.css";
import "./shared/styles/market.css";

function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>("ALL");
  const [error, setError] = useState<string>("");
  const [deferredReady, setDeferredReady] = useState(false);
  const [deferredError, setDeferredError] = useState("");

  useEffect(() => {
    let active = true;
    let deferredTimer = 0;
    loadDashboardData()
      .then((bootstrap) => {
        if (!active) return;
        setData(bootstrap as DashboardData);
        deferredTimer = window.setTimeout(() => {
          loadDeferredDashboardData()
            .then((deferred) => {
              if (!active) return;
              setData((current) => (current ? { ...current, ...deferred } : current));
              setDeferredReady(true);
            })
            .catch((reason: unknown) => {
              if (!active) return;
              setDeferredError(reason instanceof Error ? reason.message : String(reason));
            });
        }, 0);
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
    return () => {
      active = false;
      window.clearTimeout(deferredTimer);
    };
  }, []);

  if (error) {
    return <div className="state">API连接失败：{error}</div>;
  }
  if (!data) {
    return <div className="state">加载中</div>;
  }

  async function refreshData() {
    const bootstrap = await loadDashboardData();
    setData((current) => ({ ...current, ...bootstrap } as DashboardData));
    const deferred = await loadDeferredDashboardData();
    setData((current) => ({ ...current, ...deferred } as DashboardData));
    setDeferredReady(true);
    setDeferredError("");
  }

  function updateRuntimeStatus(schedulerStatus: SchedulerStatus, readiness: ReadinessReport) {
    setData((current) => (current ? mergeRuntimeStatus(current, schedulerStatus, readiness) : current));
  }

  function selectStrategy(strategyId: string) {
    setSelectedStrategyId(strategyId);
    if (strategyId === "ALL") return;
    Promise.all([getStrategy(strategyId), getStrategySeries(strategyId)])
      .then(([strategy, series]) => {
        setData((current) =>
          current
            ? {
                ...current,
                strategyDetails: { ...current.strategyDetails, [strategyId]: strategy },
                strategySeriesMap: { ...current.strategySeriesMap, [strategyId]: series }
              }
            : current
        );
      })
      .catch(() => undefined);
  }

  const context: DashboardContext = {
    ...data,
    selectedStrategyId,
    refreshData,
    selectStrategy,
    updateRuntimeStatus
  };
  const deferredPlaceholder = (
    <div className="state">{deferredError ? `页面数据加载失败：${deferredError}` : "页面数据加载中"}</div>
  );

  const router = createBrowserRouter([
    {
      path: "/",
      element: <AppLayout data={context} />,
      children: [
        { index: true, element: <DashboardPage /> },
        { path: "market", element: <MarketPage /> },
        { path: "strategies", element: deferredReady ? <StrategiesPage /> : deferredPlaceholder },
        { path: "factors", element: deferredReady ? <FactorsPage /> : deferredPlaceholder },
        { path: "runs", element: <RunsPage /> },
        { path: "scheduler", element: deferredReady ? <SchedulerPage /> : deferredPlaceholder },
        { path: "logs", element: deferredReady ? <LogsPage /> : deferredPlaceholder },
        { path: "reports", element: <ReportsPage /> },
        { path: "research", element: deferredReady ? <ResearchPage /> : deferredPlaceholder },
        { path: "data", element: <DataHealthPage /> },
        { path: "risk", element: <RiskPage /> },
        { path: "settings", element: deferredReady ? <SettingsPage /> : deferredPlaceholder }
      ]
    }
  ]);

  return <RouterProvider router={router} />;
}

export default App;
