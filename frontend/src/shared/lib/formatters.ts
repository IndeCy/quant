export type Tone = "success" | "warning" | "danger" | "neutral";

export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

export function riskTone(riskState: string | null | undefined): Tone {
  if (riskState === "REDUCED" || riskState === "FAILED") {
    return "danger";
  }
  if (riskState === "NORMAL" || riskState === "SUCCESS") {
    return "success";
  }
  if (riskState === "WATCH") {
    return "warning";
  }
  return "neutral";
}
