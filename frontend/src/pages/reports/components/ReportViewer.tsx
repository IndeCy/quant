import type { ReportContent } from "../../../entities/report/model";
import { detectReportViewerKind } from "../../../entities/report/viewer";

interface ReportViewerProps {
  report: ReportContent | null;
}

export function ReportViewer({ report }: ReportViewerProps) {
  if (!report) {
    return (
      <section className="panel report-viewer empty-viewer">
        <span>选择左侧报告查看内容</span>
      </section>
    );
  }
  const kind = detectReportViewerKind(report.file_path);
  return (
    <section className="panel report-viewer">
      <div className="viewer-header">
        <div>
          <h2>{report.title}</h2>
          <p>{report.file_path}</p>
        </div>
        <span>{kind}</span>
      </div>
      {report.missing ? <div className="missing-file">文件不存在或尚未生成</div> : <pre>{formatContent(report.content, kind)}</pre>}
    </section>
  );
}

function formatContent(content: string, kind: string): string {
  if (kind !== "json") {
    return content;
  }
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    return content;
  }
}
