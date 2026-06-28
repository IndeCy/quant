export type ReportViewerKind = "markdown" | "csv" | "json" | "text";

export function detectReportViewerKind(filePath: string): ReportViewerKind {
  const lower = filePath.toLowerCase();
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) {
    return "markdown";
  }
  if (lower.endsWith(".csv")) {
    return "csv";
  }
  if (lower.endsWith(".json")) {
    return "json";
  }
  return "text";
}
