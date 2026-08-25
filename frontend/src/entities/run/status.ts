export function runStepTone(status: string): "success" | "warning" | "failed" | "skipped" | "neutral" {
  switch (status.toUpperCase()) {
    case "SUCCESS":
      return "success";
    case "WARNING":
      return "warning";
    case "FAILED":
    case "ERROR":
      return "failed";
    case "SKIPPED":
      return "skipped";
    default:
      return "neutral";
  }
}
