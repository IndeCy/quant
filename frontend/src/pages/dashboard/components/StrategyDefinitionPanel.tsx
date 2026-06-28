import { useMemo } from "react";

import type { StrategyDefinition } from "../../../entities/strategy/model";

export function StrategyDefinitionPanel({ strategy }: { strategy: StrategyDefinition }) {
  const configRows = useMemo(() => Object.entries(strategy.config ?? {}), [strategy.config]);
  return (
    <section className="panel compact">
      <h2>策略定义</h2>
      <p>{strategy.description}</p>
      <dl>
        {configRows.map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{String(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
