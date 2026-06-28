import { PageHeader } from "../../shared/ui/PageHeader";

export function SettingsPage() {
  return (
    <>
      <PageHeader title="设置" description="后续维护 QUANT_HOME、通知、调度和备份策略。" />
      <section className="panel compact">
        <p>当前版本先提供只读控制台，设置写入能力会在调度器和备份模块完成后接入。</p>
      </section>
    </>
  );
}
