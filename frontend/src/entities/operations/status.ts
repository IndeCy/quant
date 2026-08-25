export function observationStatusTone(status: string): string {
  if (status === "PASS") {
    return "success";
  }
  if (status === "WARN") {
    return "warning";
  }
  if (status === "FAIL") {
    return "danger";
  }
  return "neutral";
}
