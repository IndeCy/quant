import type { Tone } from "../../shared/lib/formatters";
import type { MarketStyleTrendState, RelativeStyleState } from "./model";

export interface StyleDisplay {
  label: string;
  tone: Tone;
}

const TREND_DISPLAY: Record<MarketStyleTrendState, StyleDisplay> = {
  UP: { label: "多头结构", tone: "success" },
  DOWN: { label: "空头结构", tone: "danger" },
  REBOUND: { label: "反弹结构", tone: "warning" },
  WEAK: { label: "弱势震荡", tone: "warning" },
  INSUFFICIENT: { label: "样本不足", tone: "neutral" }
};

const RELATIVE_DISPLAY: Record<RelativeStyleState, StyleDisplay> = {
  MICRO_STRONG: { label: "微盘相对占优", tone: "success" },
  LARGE_STRONG: { label: "大盘相对占优", tone: "warning" },
  BALANCED: { label: "风格均衡", tone: "neutral" },
  UNKNOWN: { label: "等待数据", tone: "neutral" }
};

export function trendStyleDisplay(state: MarketStyleTrendState): StyleDisplay {
  return TREND_DISPLAY[state];
}

export function relativeStyleDisplay(state: RelativeStyleState): StyleDisplay {
  return RELATIVE_DISPLAY[state];
}
