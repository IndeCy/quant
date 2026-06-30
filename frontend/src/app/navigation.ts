import { Activity, BarChart3, BookOpenText, CalendarClock, Database, FileSearch, FileText, FlaskConical, Gauge, ScrollText, Settings } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavigationItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

export const navigationItems: NavigationItem[] = [
  { path: "/", label: "总览", icon: Gauge },
  { path: "/strategies", label: "策略", icon: BarChart3 },
  { path: "/factors", label: "因子", icon: FlaskConical },
  { path: "/runs", label: "运行", icon: Activity },
  { path: "/scheduler", label: "调度", icon: CalendarClock },
  { path: "/logs", label: "日志", icon: ScrollText },
  { path: "/reports", label: "报告", icon: FileText },
  { path: "/research", label: "研究", icon: FileSearch },
  { path: "/data", label: "数据", icon: Database },
  { path: "/risk", label: "风险", icon: BookOpenText },
  { path: "/settings", label: "设置", icon: Settings }
];
