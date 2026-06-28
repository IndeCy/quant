import type { Tone } from "../../shared/lib/formatters";

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
