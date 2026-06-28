import { useEffect, useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { AppLayout } from "./app/layout/AppLayout";
import { loadDashboardData } from "./app/loadDashboardData";
import type { DashboardData } from "./app/types";
import { DashboardPage } from "./pages/dashboard/DashboardPage";
import { DataHealthPage } from "./pages/data/DataHealthPage";
import { FactorsPage } from "./pages/factors/FactorsPage";
import { ReportsPage } from "./pages/reports/ReportsPage";
import { RiskPage } from "./pages/risk/RiskPage";
import { RunsPage } from "./pages/runs/RunsPage";
import { SettingsPage } from "./pages/settings/SettingsPage";
import { StrategiesPage } from "./pages/strategies/StrategiesPage";
import "./shared/styles/global.css";

function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    loadDashboardData()
      .then(setData)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  if (error) {
    return <div className="state">API连接失败：{error}</div>;
  }
  if (!data) {
    return <div className="state">加载中</div>;
  }

  const router = createBrowserRouter([
    {
      path: "/",
      element: <AppLayout data={data} />,
      children: [
        { index: true, element: <DashboardPage /> },
        { path: "strategies", element: <StrategiesPage /> },
        { path: "factors", element: <FactorsPage /> },
        { path: "runs", element: <RunsPage /> },
        { path: "reports", element: <ReportsPage /> },
        { path: "data", element: <DataHealthPage /> },
        { path: "risk", element: <RiskPage /> },
        { path: "settings", element: <SettingsPage /> }
      ]
    }
  ]);

  return <RouterProvider router={router} />;
}

export default App;
