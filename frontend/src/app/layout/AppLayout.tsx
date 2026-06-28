import { Outlet } from "react-router-dom";

import type { DashboardData } from "../types";
import { Sidebar } from "./Sidebar";
import { TopStatusBar } from "./TopStatusBar";

interface AppLayoutProps {
  data: DashboardData;
}

export function AppLayout({ data }: AppLayoutProps) {
  return (
    <div className="app-shell">
      <Sidebar />
      <section className="main-shell">
        <TopStatusBar strategy={data.strategy} />
        <Outlet context={data} />
      </section>
    </div>
  );
}
