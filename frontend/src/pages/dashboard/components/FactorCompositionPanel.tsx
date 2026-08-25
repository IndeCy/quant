import type { FactorDefinition } from "../../../entities/factor/model";
import { formatPercent } from "../../../shared/lib/formatters";

export function FactorCompositionPanel({ factors }: { factors: FactorDefinition[] }) {
  return (
    <section className="panel compact">
      <h2>因子组合</h2>
      <div className="factor-list">
        {factors.map((factor) => (
          <div className="factor-row" key={factor.factor_id}>
            <strong>{factor.name}</strong>
            <span>
              {formatPercent(factor.weight, 1)} / {factor.transform}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
